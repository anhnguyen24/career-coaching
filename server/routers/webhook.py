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
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.scorer import Scorer

router = APIRouter()

# ============================================================
# Survey auto-detection — always uses latest version
# ============================================================

def _get_latest_survey_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        Path("/app/src/survey_versions"),
        here.parent.parent / "src" / "survey_versions",
        here.parent.parent.parent / "src" / "survey_versions",
        Path.cwd() / "src" / "survey_versions",
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
    import json
    path = _get_latest_survey_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_scorer() -> Scorer:
    return Scorer(_load_latest_survey())


def _get_survey_version() -> str:
    path = _get_latest_survey_path()
    return path.stem.replace("survey_", "")


WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _verify_secret(secret: str):
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


STUDENT_INFO_COLS = 16
TOTAL_QUESTIONS   = 180


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
    response_row: List[Any]

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "response_row": ["2026-01-01", "Tên HS", "HN-2026-0007", "...15 more info cols...", 3, 4, 4]
            }
        }


class MBTIAxis(BaseModel):
    winner: str
    gap: float
    scores: Dict[str, float]


class MBTI(BaseModel):
    type: str
    clarity: str
    gap_avg: float
    note: str
    axes: Dict[str, MBTIAxis]


class Holland(BaseModel):
    top3: List[str]
    top3_label: str
    groups: Dict[str, float]


class Ocean(BaseModel):
    groups: Dict[str, float]


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


def _build_response(token: str, answers: Dict[int, int]) -> ScoreResponse:
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

    axes = {}
    for ax in mbti_d.get("axes", []):
        key = ax["group_a"]["id"] + ax["group_b"]["id"]
        axes[key] = MBTIAxis(
            winner=ax["winner"],
            gap=ax["gap"],
            scores={
                ax["group_a"]["id"]: ax["group_a"]["score"],
                ax["group_b"]["id"]: ax["group_b"]["score"],
            }
        )

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


@router.post("/score", response_model=ScoreResponse)
def score(
    payload: ScoreRequest,
    x_webhook_secret: str = Header(default=""),
):
    _verify_secret(x_webhook_secret)
    return _build_response(payload.token, payload.answers)


@router.post("/score-raw", response_model=ScoreResponse)
def score_raw(
    payload: ScoreRawRequest,
    x_webhook_secret: str = Header(default=""),
):
    _verify_secret(x_webhook_secret)

    row = payload.response_row
    expected_min = STUDENT_INFO_COLS + TOTAL_QUESTIONS

    if len(row) < expected_min:
        raise HTTPException(
            status_code=400,
            detail=f"Row too short: expected at least {expected_min} columns, got {len(row)}"
        )

    answers = {
        i + 1: int(row[STUDENT_INFO_COLS + i])
        for i in range(TOTAL_QUESTIONS)
    }

    return _build_response(payload.token, answers)


def _extract_answers_from_row(row: List[Any]) -> Dict[int, int]:
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


def _student_info_from_row(row: List[Any]) -> Dict[str, Any]:
    """Shared helper — same student_info shape used by every endpoint
    that calls into services/report.py or services/portraits.py."""
    return {
        "name":          row[1]  if len(row) > 1  else "",
        "grade":         row[5]  if len(row) > 5  else "",
        "school":        row[7]  if len(row) > 7  else "",
        "direction":     row[11] if len(row) > 11 else "",
        "after_school":  row[12] if len(row) > 12 else "",
        "fav_subjects":  row[13] if len(row) > 13 else "",
        "fav_activities":row[14] if len(row) > 14 else "",
    }


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
    _verify_secret(x_webhook_secret)

    from services.report import markdown_to_docx_base64

    try:
        docx_b64 = markdown_to_docx_base64(payload.markdown_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docx conversion failed: {str(e)}")

    return MarkdownToDocxResponse(docx_base64=docx_b64)


@router.post("/test-report-stream")
def test_report_stream(
    payload: TestReportRequest,
    x_webhook_secret: str = Header(default=""),
):
    _verify_secret(x_webhook_secret)

    row     = payload.response_row
    answers = _extract_answers_from_row(row)
    scores_response = _build_response(payload.token, answers)
    student_info = _student_info_from_row(row)

    from services.report import generate_report_stream

    def stream_wrapper():
        try:
            for chunk in generate_report_stream(student_info, scores_response.model_dump()):
                yield chunk
        except Exception as e:
            yield f"\n\n===ERROR===\n{str(e)}"

    return StreamingResponse(stream_wrapper(), media_type="text/plain")


@router.post("/test-report", response_model=TestReportResponse)
def test_report(
    payload: TestReportRequest,
    x_webhook_secret: str = Header(default=""),
):
    _verify_secret(x_webhook_secret)

    row     = payload.response_row
    answers = _extract_answers_from_row(row)
    scores_response = _build_response(payload.token, answers)
    student_info = _student_info_from_row(row)

    from services.report import generate_report

    try:
        result = generate_report(student_info, scores_response.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")

    return TestReportResponse(**result)


class GeneratePortraitsRequest(BaseModel):
    token: str
    response_row: List[Any]

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "response_row": ["2026-01-01", "Tên HS", "HN-2026-0007", "...15 more info cols...", 3, 4, 4]
            }
        }


class GeneratePortraitsResponse(BaseModel):
    portrait_text: str
    score_matched: str | None
    logic_summary: str
    student_portraits: str
    mirror_question: str
    consultant_note: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    truncated: bool


@router.post("/generate-portraits", response_model=GeneratePortraitsResponse)
def generate_portraits(
    payload: GeneratePortraitsRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Generate 3 micro-portraits for the Mirror Check step.

    Returns the full 4-section portrait text (portrait_text), the same
    text split into its 4 sections (logic_summary, student_portraits,
    mirror_question, consultant_note), and which portrait (A/B/C) the
    system considers score-matched.

    Cost: ~$0.05–$0.12 per call.
    """
    _verify_secret(x_webhook_secret)

    row     = payload.response_row
    answers = _extract_answers_from_row(row)
    scores_response = _build_response(payload.token, answers)
    student_info = _student_info_from_row(row)

    from services.portraits import generate_portraits as _gen_portraits

    try:
        result = _gen_portraits(student_info, scores_response.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portrait generation failed: {str(e)}")

    return GeneratePortraitsResponse(**result)


# ============================================================
# Final report — async generation with callback
#
# Report generation (Claude Opus, full SOP + Master Router) can take
# 5-6 minutes. Apps Script's own execution has a hard ~6 minute cap, so
# it CANNOT wait synchronously for this the way /generate-portraits
# (a much faster Sonnet call) can be waited on. Instead:
#
#   1. Apps Script POSTs here with a callback_url (its own Web App URL).
#   2. This endpoint starts generation in a background thread and
#      returns {"status": "started"} immediately — no waiting.
#   3. Apps Script's execution ends right there; nothing is blocked.
#   4. Minutes later, once generation finishes, the background thread
#      POSTs the result (or an error) to callback_url on its own.
#   5. Apps Script's doPost() receives that callback as a brand new,
#      separate execution — decodes the docx, saves it to Drive,
#      updates the tracking sheet. See mirror_check_response_trigger.gs.
#
# No in-memory job-status tracking is needed on this side since nothing
# polls this endpoint — the callback is a one-shot push, not something
# Apps Script asks about repeatedly.
# ============================================================

class MirrorCheckData(BaseModel):
    """
    Mirror Check inputs required by the V4.2 Master Router / Siêu Prompt
    2.5 prompts. All fields optional — a student who hasn't completed
    Mirror Check yet still gets a report, per the SOP's explicit
    fallback ("Chưa có dữ liệu self-confirmation..."), just with this
    whole object omitted from the request.
    """
    score_matched: Optional[str] = None
    student_choice: Optional[str] = None
    mirror_fit_color: Optional[str] = None
    mirror_fit_level: Optional[str] = None
    highlight_answer: Optional[str] = None
    mismatch_answer: Optional[str] = None
    aspiration_answer: Optional[str] = None


class TranscriptFile(BaseModel):
    """
    One transcript/report-card file (PDF or image), base64-encoded by
    Apps Script from a Drive attachment. Validated further server-side
    against a mime-type whitelist and size caps in
    services/report.py's _build_transcript_content_blocks() — this
    model just defines the wire shape, doesn't enforce those rules
    itself, so a rejected file here still arrives as a normal request
    rather than a 422 (rejection happens gracefully downstream, with a
    log line, not by failing the whole request).
    """
    filename: str
    mime_type: str
    data: str  # base64-encoded file bytes


class GenerateReportAsyncRequest(BaseModel):
    token: str
    response_row: List[Any]
    mirror_check: Optional[MirrorCheckData] = None
    transcript_files: Optional[List[TranscriptFile]] = None
    callback_url: str
    callback_secret: str

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "response_row": ["2026-01-01", "Tên HS", "HN-2026-0007", "...15 more info cols...", 3, 4, 4],
                "mirror_check": {
                    "score_matched": "A",
                    "student_choice": "A",
                    "mirror_fit_color": "Xanh",
                    "mirror_fit_level": "High Fit",
                    "highlight_answer": "Câu về việc thích tự làm sản phẩm",
                    "mismatch_answer": "",
                },
                "transcript_files": [
                    {"filename": "phieu_diem.jpg", "mime_type": "image/jpeg", "data": "<base64>"}
                ],
                "callback_url": "https://script.google.com/macros/s/XXXXX/exec",
                "callback_secret": "same-value-as-WEBHOOK_SECRET",
            }
        }


class GenerateReportAsyncResponse(BaseModel):
    status: str


@router.post("/generate-report-async", response_model=GenerateReportAsyncResponse)
def generate_report_async_endpoint(
    payload: GenerateReportAsyncRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Kicks off full career report generation in the background and
    returns immediately. The actual result is delivered later via a
    POST to payload.callback_url (see module docstring above).

    callback_secret is caller-supplied (Apps Script sends its own
    WEBHOOK_SECRET value back as the expected header on the callback)
    rather than reusing X-Webhook-Secret directly, so the callback
    verification is self-contained in the payload and doesn't depend
    on this endpoint's own auth mechanism staying identical over time.
    """
    _verify_secret(x_webhook_secret)

    row = payload.response_row

    try:
        answers = _extract_answers_from_row(row)
        scores_response = _build_response(payload.token, answers)
        student_info = _student_info_from_row(row)
    except HTTPException:
        raise  # preserve the specific 400/500 + detail from these helpers
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to score/extract student info from response_row before "
                    f"starting report generation: {type(e).__name__}: {str(e)}"
        )

    mirror_check_dict = payload.mirror_check.model_dump() if payload.mirror_check else None
    transcript_files_list = (
        [f.model_dump() for f in payload.transcript_files] if payload.transcript_files else None
    )

    from services.report import generate_report_async

    try:
        generate_report_async(
            student_info=student_info,
            scores=scores_response.model_dump(),
            mirror_check=mirror_check_dict,
            transcript_files=transcript_files_list,
            token=payload.token,
            callback_url=payload.callback_url,
            callback_secret=payload.callback_secret,
        )
    except Exception as e:
        # This only catches failure to START the background thread itself
        # (extremely unlikely) — failures DURING generation are caught
        # inside the thread and reported via the callback instead, since
        # by then this request has already returned.
        raise HTTPException(status_code=500, detail=f"Failed to start report generation: {str(e)}")

    return GenerateReportAsyncResponse(status="started")


# ============================================================
# Post-test (UX/experience feedback) survey scoring
#
# Replaces the legacy in-sheet formula approach in the post-test
# spreadsheet's "Scores" tab, which was found to contain real bugs —
# see services/post_test_scorer.py's module docstring for the full
# audit findings (UX Score undercounted, TimeScore/LengthPain off by
# one, QualityFlag fully inverted). All scoring logic now lives in
# testable Python instead of copy-down spreadsheet formulas.
# ============================================================

class ScorePostTestRequest(BaseModel):
    response_row: List[Any]

    class Config:
        json_schema_extra = {
            "example": {
                "response_row": ["2026-07-10 16:49", "Hoàng Hải Phong", 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
                                  "TEST 3", "Không phần nào khó", "Nghĩ vừa vừa", "15–25 phút", "90 câu", "Không",
                                  "70–80%", "", "", "", "", "HN-2026-0012"]
            }
        }


class PostTestUX(BaseModel):
    score: int
    min: int
    max: int
    avg: float
    level: str
    answers: List[int]


class PostTestQuickSelect(BaseModel):
    most_tired_part: str
    hardest_part: str
    fatigue_answer: str
    fatigue_score: int
    time_answer: str
    time_score: int
    length_answer: str
    length_pain: int
    quality_flag_answer: str
    quality_flag: int
    confidence_answer: str
    confidence_score: int


class PostTestOpenAnswers(BaseModel):
    q22_confusing_wording: str
    q23_sensitive: str
    q25_repetitive: str
    q26_suggestion: str
    note: str


class ScorePostTestResponse(BaseModel):
    token: str
    student_name: str
    ux: PostTestUX
    quick_select: PostTestQuickSelect
    data_quality_score: int
    data_quality_note: str
    open_answers: PostTestOpenAnswers


@router.post("/score-post-test", response_model=ScorePostTestResponse)
def score_post_test_endpoint(
    payload: ScorePostTestRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Score a post-test (UX/experience feedback) survey submission from
    its raw response row. See services/post_test_scorer.py for the
    full scoring logic and the design document it implements.

    Returns HTTP 400 (not 500) if a Part B answer doesn't exactly
    match any known option string — this means the live form's option
    text changed and the lookup tables in post_test_scorer.py need
    updating, not a transient server error.
    """
    _verify_secret(x_webhook_secret)

    from services.post_test_scorer import score_post_test, PostTestScoringError

    try:
        result = score_post_test(payload.response_row)
    except PostTestScoringError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Post-test scoring failed: {str(e)}")

    return ScorePostTestResponse(**result)
