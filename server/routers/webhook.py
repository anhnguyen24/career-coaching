"""
server/routers/webhook.py — Webhook endpoints called by Apps Script

POST /webhook/score
    Receives token + 180 answers from Apps Script onFormSubmit
    Runs scorer.py and returns all scores
    Apps Script uses the returned scores to generate the Google Doc
"""

import os
import json
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from services.scorer import Scorer

router = APIRouter()

# ============================================================
# Load survey from environment or default path
# ============================================================
def _get_latest_survey_path() -> Path:
    survey_dir = Path(__file__).parent.parent.parent / "src" / "survey_versions"
    survey_files = sorted(survey_dir.glob("survey_v*.json"))
    if not survey_files:
        raise HTTPException(status_code=500, detail="No survey JSON found in src/survey_versions/")
    return survey_files[-1]

def _get_scorer() -> Scorer:
    return Scorer.from_file(_get_latest_survey_path())


# ============================================================
# Auth — simple shared secret
# ============================================================
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

def _verify_secret(x_webhook_secret: str = Header(default="")):
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# ============================================================
# Models
# ============================================================

class ScoreRequest(BaseModel):
    token: str
    survey_version: str
    answers: Dict[int, int]  # {question_number: score}

    class Config:
        json_schema_extra = {
            "example": {
                "token": "HN-2026-0007",
                "survey_version": "v2",
                "answers": {
                    1: 3, 2: 4, 3: 4
                }
            }
        }


class AxisScore(BaseModel):
    id: str
    score: float


class MBTIAxisResult(BaseModel):
    axis: str
    group_a: AxisScore
    group_b: AxisScore
    winner: str
    gap: float


class MBTIScore(BaseModel):
    type: str
    gap_avg: float
    clarity: str
    note: str
    axes: list[MBTIAxisResult]


class GroupScore(BaseModel):
    id: str
    name: str
    score: float


class HollandScore(BaseModel):
    top3: list[str]
    top3_label: str
    groups: list[GroupScore]


class OceanScore(BaseModel):
    groups: list[GroupScore]


class CompositeScore(BaseModel):
    id: str
    name: str
    label: str
    score: float
    interpretation: str


class ScoreResponse(BaseModel):
    token: str
    survey_version: str
    mbti: MBTIScore
    holland: HollandScore
    ocean: OceanScore
    composite_scores: list[CompositeScore]


# ============================================================
# Endpoints
# ============================================================

@router.post("/score", response_model=ScoreResponse)
def score_submission(
    payload: ScoreRequest,
    x_webhook_secret: str = Header(default=""),
):
    """
    Score a survey submission.

    Called by Apps Script onFormSubmit with the student's 180 answers.
    Returns all scores (MBTI, Holland, OCEAN, SSS) ready for doc generation.

    Apps Script usage:
        var response = UrlFetchApp.fetch(SERVER_URL + '/webhook/score', {
            method: 'post',
            contentType: 'application/json',
            headers: { 'X-Webhook-Secret': WEBHOOK_SECRET },
            payload: JSON.stringify({
                token: token,
                survey_version: 'v2',
                answers: answersObj
            })
        });
        var scores = JSON.parse(response.getContentText());
    """
    _verify_secret(x_webhook_secret)

    # Validate answer count
    total_expected = 180
    if len(payload.answers) != total_expected:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {total_expected} answers, got {len(payload.answers)}"
        )

    # Run scorer
    try:
        scorer  = _get_scorer()
        result  = scorer.score(payload.answers)
        result_dict = result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scoring failed: {str(e)}")

    # Build response
    mbti = result_dict.get("mbti", {})
    holland = result_dict.get("holland", {})
    ocean = result_dict.get("ocean", {})
    composites = result_dict.get("composite_scores", [])

    return ScoreResponse(
        token=payload.token,
        survey_version=payload.survey_version,
        mbti=MBTIScore(
            type=mbti.get("type", ""),
            gap_avg=mbti.get("gap_avg", 0),
            clarity=mbti.get("clarity", ""),
            note=mbti.get("note", ""),
            axes=[
                MBTIAxisResult(
                    axis=ax["axis"],
                    group_a=AxisScore(id=ax["group_a"]["id"], score=ax["group_a"]["score"]),
                    group_b=AxisScore(id=ax["group_b"]["id"], score=ax["group_b"]["score"]),
                    winner=ax["winner"],
                    gap=ax["gap"],
                )
                for ax in mbti.get("axes", [])
            ],
        ),
        holland=HollandScore(
            top3=holland.get("top3", []),
            top3_label=holland.get("top3_label", ""),
            groups=[
                GroupScore(id=g["id"], name=g["name"], score=g["score"])
                for g in holland.get("groups", [])
            ],
        ),
        ocean=OceanScore(
            groups=[
                GroupScore(id=g["id"], name=g["name"], score=g["score"])
                for g in ocean.get("groups", [])
            ],
        ),
        composite_scores=[
            CompositeScore(
                id=cs["id"],
                name=cs["name"],
                label=cs["label"],
                score=cs["score"],
                interpretation=cs["interpretation"],
            )
            for cs in composites
        ],
    )
