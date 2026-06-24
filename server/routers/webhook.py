"""
server/routers/webhook.py — Webhook endpoints called by Apps Script

POST /webhook/score
    Receives token + answers dict {question_number: score}
    Returns structured scores with named keys

POST /webhook/score-raw
    Receives token + raw Form Responses row (full array)
    Extracts answers automatically, returns same structured scores
    Easier to call from Apps Script — just pass responseData directly
"""

import os
from pathlib import Path
from typing import Dict, List, Any

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from services.scorer import Scorer

router = APIRouter()

# ============================================================
# Survey auto-detection — always uses latest version
# ============================================================

def _get_latest_survey_path() -> Path:
    """
    Find the latest survey_vN.json file. Tries multiple candidate
    locations since the exact relative depth depends on how the
    Docker image was built (and to be safe across local vs container).
    """
    here = Path(__file__).resolve()
    candidates = [
        Path("/app/src/survey_versions"),                     # Docker: WORKDIR /app, src/ copied alongside
        here.parent.parent / "src" / "survey_versions",       # server/ as cwd: routers/.. -> server/src (rare)
        here.parent.parent.parent / "src" / "survey_versions",# repo_root/src (local dev: repo_root/server/routers/..)
        Path.cwd() / "src" / "survey_versions",                # fallback: relative to current working dir
    ]

    tried = []
    for survey_dir in candidates:
        tried.append(str(survey_dir))
        if survey_dir.exists():
            survey_files = sorted(survey_dir.glob("survey_v*.json"))
            if survey_files:
                return survey_files[-1]

    raise HTTPException(
        status_code=500,
        detail=f"No survey JSON found. Tried: {tried}"
    )


def _load_latest_survey() -> dict:
    """Load the full survey JSON dict (used by both Scorer and DocGenerator)."""
    import json
    path = _get_latest_survey_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_scorer() -> Scorer:
    return Scorer(_load_latest_survey())


def _get_survey_version() -> str:
    path = _get_latest_survey_path()
    # Extract version from filename e.g. survey_v2.json → v2
    return path.stem.replace("survey_", "")


# ============================================================
# Auth — simple shared secret
# ============================================================

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _verify_secret(secret: str):
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# ============================================================
# Column layout in Form Responses 2
# Timestamp + 15 student info fields = 16 columns before Q1
# ============================================================

STUDENT_INFO_COLS = 16  # columns 0-15
TOTAL_QUESTIONS   = 180


# ============================================================
# Request models
# ============================================================

class ScoreRequest(BaseModel):
    token: str
    answers: Dict[int, int]

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "answers": {1: 3, 2: 4, 3: 4}
            }
        }


class ScoreRawRequest(BaseModel):
    token: str
    response_row: List[Any]  # full row from Form Responses 2

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "response_row": ["2026-01-01", "Tên HS", "HN-2026-0007", "...15 more info cols...", 3, 4, 4]
            }
        }


# ============================================================
# Response models — named keys, no magic indices
# ============================================================

class MBTIAxis(BaseModel):
    winner: str
    gap: float
    scores: Dict[str, float]   # e.g. {"E": 3.5, "I": 1.67}


class MBTI(BaseModel):
    type: str                  # e.g. "ENTP"
    clarity: str               # e.g. "Khá rõ"
    gap_avg: float
    note: str
    axes: Dict[str, MBTIAxis]  # e.g. {"EI": {...}, "SN": {...}}


class Holland(BaseModel):
    top3: List[str]            # e.g. ["S", "A", "C"]
    top3_label: str            # e.g. "SAC"
    groups: Dict[str, float]   # e.g. {"R": 25, "I": 34, ...}


class Ocean(BaseModel):
    groups: Dict[str, float]   # e.g. {"O": 4.25, "C": 4.33, ...}


class SSSComponents(BaseModel):
    mbti_social_score: float
    ocean_e_avg: float
    raw_social_score: float


class SSS(BaseModel):
    score: float
    interpretation: str
    components: SSSComponents


class ScoreResponse(BaseModel):
    token: str
    survey_version: str
    mbti: MBTI
    holland: Holland
    ocean: Ocean
    sss: SSS


# ============================================================
# Shared scoring logic
# ============================================================

def _build_response(token: str, answers: Dict[int, int]) -> ScoreResponse:
    """Run scorer and build the structured response."""
    if len(answers) != TOTAL_QUESTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {TOTAL_QUESTIONS} answers, got {len(answers)}"
        )

    try:
        scorer  = _get_scorer()
        result  = scorer.score(answers)
        d       = result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scoring failed: {str(e)}")

    mbti_d    = d.get("mbti", {})
    holland_d = d.get("holland", {})
    ocean_d   = d.get("ocean", {})
    sss_d     = next((cs for cs in d.get("composite_scores", []) if cs["id"] == "sss"), {})

    # Build MBTI axes dict
    axes = {}
    for ax in mbti_d.get("axes", []):
        key = ax["group_a"]["id"] + ax["group_b"]["id"]   # e.g. "EI"
        axes[key] = MBTIAxis(
            winner=ax["winner"],
            gap=ax["gap"],
            scores={
                ax["group_a"]["id"]: ax["group_a"]["score"],
                ax["group_b"]["id"]: ax["group_b"]["score"],
            }
        )

    # Build SSS components
    components_raw = {c["source"]: c["raw_value"] for c in sss_d.get("components", [])}
    sss_components = SSSComponents(
        mbti_social_score=components_raw.get("bipolar_ratio", 0),
        ocean_e_avg=components_raw.get("test_group", 0),
        raw_social_score=components_raw.get("question_subset", 0),
    )

    return ScoreResponse(
        token=token,
        survey_version=_get_survey_version(),
        mbti=MBTI(
            type=mbti_d.get("type", ""),
            clarity=mbti_d.get("clarity", ""),
            gap_avg=mbti_d.get("gap_avg", 0),
            note=mbti_d.get("note", ""),
            axes=axes,
        ),
        holland=Holland(
            top3=holland_d.get("top3", []),
            top3_label=holland_d.get("top3_label", ""),
            groups={g["id"]: g["score"] for g in holland_d.get("groups", [])},
        ),
        ocean=Ocean(
            groups={g["id"]: g["score"] for g in ocean_d.get("groups", [])},
        ),
        sss=SSS(
            score=sss_d.get("score", 0),
            interpretation=sss_d.get("interpretation", ""),
            components=sss_components,
        ),
    )


# ============================================================
# Endpoints
# ============================================================

@router.post("/score", response_model=ScoreResponse)
def score(
    payload: ScoreRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Score a survey submission from a pre-built answers dict.

    Apps Script usage:
        var answersObj = {};
        for (var i = 0; i < 180; i++) {
            answersObj[i + 1] = responseData[16 + i];
        }
        var response = UrlFetchApp.fetch(SERVER_URL + '/webhook/score', {
            method: 'post',
            contentType: 'application/json',
            headers: { 'X-Webhook-Secret': WEBHOOK_SECRET },
            payload: JSON.stringify({ token: token, answers: answersObj })
        });
        var scores = JSON.parse(response.getContentText());
        // Access: scores.mbti.type, scores.holland.top3_label, scores.sss.score
    """
    _verify_secret(x_webhook_secret)
    return _build_response(payload.token, payload.answers)


@router.post("/score-raw", response_model=ScoreResponse)
def score_raw(
    payload: ScoreRawRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Score a survey submission from a raw Form Responses row.
    Extracts answers from columns 16-195 automatically.

    Apps Script usage (simplest — just pass the whole row):
        var response = UrlFetchApp.fetch(SERVER_URL + '/webhook/score-raw', {
            method: 'post',
            contentType: 'application/json',
            headers: { 'X-Webhook-Secret': WEBHOOK_SECRET },
            payload: JSON.stringify({
                token: token,
                response_row: responseData
            })
        });
        var scores = JSON.parse(response.getContentText());
        // Access: scores.mbti.type, scores.holland.top3_label, scores.sss.score
    """
    _verify_secret(x_webhook_secret)

    row = payload.response_row
    expected_min = STUDENT_INFO_COLS + TOTAL_QUESTIONS

    if len(row) < expected_min:
        raise HTTPException(
            status_code=400,
            detail=f"Row too short: expected at least {expected_min} columns, got {len(row)}"
        )

    # Extract answers from columns 16-195 (0-based)
    answers = {
        i + 1: int(row[STUDENT_INFO_COLS + i])
        for i in range(TOTAL_QUESTIONS)
    }

    return _build_response(payload.token, answers)


def _extract_answers_from_row(row: List[Any]) -> Dict[int, int]:
    """Shared helper: extract the 180 answers from a raw response row."""
    expected_min = STUDENT_INFO_COLS + TOTAL_QUESTIONS
    if len(row) < expected_min:
        raise HTTPException(
            status_code=400,
            detail=f"Row too short: expected at least {expected_min} columns, got {len(row)}"
        )
    return {
        i + 1: int(row[STUDENT_INFO_COLS + i])
        for i in range(TOTAL_QUESTIONS)
    }


# ============================================================
# TEST/DEV — full AI report generation with real Opus call
# ============================================================

class TestReportRequest(BaseModel):
    token: str
    response_row: List[Any]

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "response_row": ["2026-01-01", "Tên HS", "HN-2026-0007", "...15 more info cols...", 3, 4, 4]
            }
        }


class TestReportResponse(BaseModel):
    report_text: str
    docx_base64: str | None = None
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


# ============================================================
# TEST/DEV — markdown-to-docx conversion ONLY (no API call, free)
# ============================================================

class MarkdownToDocxRequest(BaseModel):
    markdown_text: str

    class Config:
        json_schema_extra = {
            "example": {
                "markdown_text": "# Hello\n\nThis is **bold** text.\n\n| A | B |\n|---|---|\n| 1 | 2 |"
            }
        }


class MarkdownToDocxResponse(BaseModel):
    docx_base64: str


@router.post("/markdown-to-docx", response_model=MarkdownToDocxResponse)
def markdown_to_docx(
    payload: MarkdownToDocxRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    DEV/TEST ONLY — converts markdown text to a .docx file via pandoc,
    no Anthropic API call involved (zero cost). Use this to verify the
    pandoc pipeline runs correctly inside the deployed container, using
    any markdown text you already have (e.g. a previously generated
    report), without spending tokens on a new generation.
    """
    _verify_secret(x_webhook_secret)

    from services.report import markdown_to_docx_base64

    try:
        docx_b64 = markdown_to_docx_base64(payload.markdown_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docx conversion failed: {str(e)}")

    return MarkdownToDocxResponse(docx_base64=docx_b64)


@router.post("/test-report", response_model=TestReportResponse)
def test_report(
    payload: TestReportRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    DEV/TEST ONLY — calls the real Anthropic API directly with the full
    career report SOP and real student scores, using Claude Opus with
    a generous token budget (no artificial cap).

    Use this to measure real cost and quality before committing to a
    production architecture. NOT wired into the student-facing pipeline —
    Apps Script still owns doc creation for now.

    Requires ANTHROPIC_API_KEY environment variable on the server.
    """
    _verify_secret(x_webhook_secret)

    row     = payload.response_row
    answers = _extract_answers_from_row(row)
    scores_response = _build_response(payload.token, answers)

    student_info = {
        "name":          row[1]  if len(row) > 1  else "",
        "grade":         row[5]  if len(row) > 5  else "",
        "school":        row[7]  if len(row) > 7  else "",
        "direction":     row[11] if len(row) > 11 else "",
        "after_school":  row[12] if len(row) > 12 else "",
        "fav_subjects":  row[13] if len(row) > 13 else "",
        "fav_activities":row[14] if len(row) > 14 else "",
    }

    from services.report import generate_report

    try:
        result = generate_report(student_info, scores_response.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")

    return TestReportResponse(**result)

