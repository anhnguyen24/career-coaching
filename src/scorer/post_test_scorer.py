"""
server/services/post_test_scorer.py — Post-test (UX/experience feedback)
survey scoring.

Replaces the legacy in-sheet formula approach (copy-formula-down in the
"Scores" tab of the post-test spreadsheet), which was found to contain
real bugs — confirmed by manually auditing token HN-2026-0012:
  - UX Score undercounted by 3 points (65/70 shown vs. 68/70 actual sum
    of the 14 displayed answers)
  - TimeScore and LengthPain each read 1 point too low for their actual
    selected option
  - QualityFlag fully inverted ("Không" read as if "Có")
The DataQualityScore *combining* formula itself
(Confidence - Fatigue - Time - Length - QualityFlag) was verified
correct — only the individual component lookups were wrong. The
lookup-table dicts below use the option strings copied directly from
the live Google Form (confirmed via screenshot), not the shorthand
notation in the original design document (e.g. the design doc's
"15-25'" vs. the form's actual "15–25 phút") — a mismatch between
those two is the leading suspect for how the original formula broke.

Source of truth for this scoring logic: "BỘ CÂU HỎI ĐO TRẢI NGHIỆM
NGƯỜI LÀM TEST NGAY SAU KHI TEST VÀ CÁCH TÍNH ĐIỂM" (the post-test
design document).
"""

from typing import Any, Dict, List, Optional

# ============================================================
# Column layout in the post-test Form Responses sheet (0-based)
# Confirmed from the existing Apps Script's appendPostTestToDoc().
# ============================================================
COL_TIMESTAMP     = 0
COL_NAME          = 1
COL_PART_A_START  = 2   # Câu 1-14 occupy columns 2 through 15 inclusive (14 cols)
COL_PART_A_COUNT  = 14
COL_Q15_TIRED     = 16
COL_Q16_HARD      = 17
COL_Q17_FATIGUE   = 18
COL_Q18_TIME      = 19
COL_Q19_LENGTH    = 20
COL_Q20_QUALITY   = 21
COL_Q21_CONFIDENCE = 22
COL_Q22_OPEN      = 23
COL_Q23_OPEN      = 24
COL_Q25_OPEN      = 25
COL_Q26_OPEN      = 26
COL_TOKEN         = 27

TOTAL_PART_A_QUESTIONS = 14
UX_MIN = 14
UX_MAX = 70

# ============================================================
# Part B lookup tables — option strings copied EXACTLY from the live
# Google Form (verified via screenshot on 2026-07-11), not from the
# original design doc's shorthand notation. Exact-match dict lookups
# here are deliberate: unlike a spreadsheet VLOOKUP (which silently
# falls back to an approximate match if the exact-match flag is
# omitted — the likely root cause of the original bug), a Python dict
# lookup with no matching key raises immediately rather than silently
# returning a wrong neighboring value.
# ============================================================

FATIGUE_MAP = {
    "Chọn nhanh": 0,
    "Nghĩ vừa vừa": 1,
    "Nghĩ lâu": 2,
    "Có lúc tick đại vì mệt": 4,
}

TIME_MAP = {
    "<15 phút": 3,
    "15–25 phút": 1,
    "25–35 phút": 0,
    ">35 phút": 2,
}

LENGTH_MAP = {
    "60 câu": 3,
    "90 câu": 2,
    "120 câu": 1,
    "180 câu (giữ nguyên)": 0,
}

QUALITY_FLAG_MAP = {
    "Có": 4,
    "Không": 0,
    "Không nhớ": 2,
}

CONFIDENCE_MAP = {
    "0–30%": 0,
    "40–60%": 1,
    "70–80%": 2,
    "90–100%": 3,
}


class PostTestScoringError(Exception):
    """Raised when a Part B answer doesn't exactly match any known
    option string — surfaces loudly instead of silently defaulting to
    a wrong value (which is exactly the failure mode this migration is
    meant to eliminate)."""
    pass


def _lookup(mapping: Dict[str, int], value: Any, field_name: str) -> int:
    key = str(value or "").strip()
    if key not in mapping:
        raise PostTestScoringError(
            f"Unrecognized {field_name} answer: {key!r}. "
            f"Expected one of: {list(mapping.keys())}. "
            f"This usually means the live form's option text changed and "
            f"this lookup table needs updating to match."
        )
    return mapping[key]


def _ux_level(avg: float) -> str:
    if avg >= 4.2:
        return "Rất mượt"
    if avg >= 3.6:
        return "Ổn, nên chỉnh vài câu chữ/độ dài"
    return "Học sinh mệt/khó hiểu, nên rút gọn hoặc chia phase"


def score_post_test(response_row: List[Any]) -> Dict[str, Any]:
    """
    Score a post-test (UX/experience feedback) survey submission from
    its raw response row, per the official design document's formulas.

    Part C (open-ended questions 22/23/25/26) is intentionally NOT
    auto-scored here — the design doc specifies OpenPainScore and
    SuggestionQualityScore require manual 0-2 grading based on judging
    the actual content of free-text answers, which isn't something to
    automate. The raw text is passed through for the consultant to
    read and grade by hand, same as the current workflow.
    """
    if len(response_row) <= COL_TOKEN:
        raise PostTestScoringError(
            f"Row too short: expected at least {COL_TOKEN + 1} columns, got {len(response_row)}"
        )

    # --- Part A: UX Score ---
    part_a_answers = []
    for i in range(TOTAL_PART_A_QUESTIONS):
        raw = response_row[COL_PART_A_START + i]
        try:
            part_a_answers.append(int(raw))
        except (TypeError, ValueError):
            raise PostTestScoringError(
                f"Part A câu {i + 1}: expected a 1-5 rating, got {raw!r}"
            )

    ux_score = sum(part_a_answers)
    ux_avg = round(ux_score / TOTAL_PART_A_QUESTIONS, 4)
    ux_level = _ux_level(ux_avg)

    # --- Part B: component scores + DataQualityScore ---
    fatigue_score = _lookup(FATIGUE_MAP, response_row[COL_Q17_FATIGUE], "Câu 17 (FatigueScore)")
    time_score = _lookup(TIME_MAP, response_row[COL_Q18_TIME], "Câu 18 (TimeScore)")
    length_pain = _lookup(LENGTH_MAP, response_row[COL_Q19_LENGTH], "Câu 19 (LengthPain)")
    quality_flag = _lookup(QUALITY_FLAG_MAP, response_row[COL_Q20_QUALITY], "Câu 20 (QualityFlag)")
    confidence_score = _lookup(CONFIDENCE_MAP, response_row[COL_Q21_CONFIDENCE], "Câu 21 (ConfidenceScore)")

    data_quality_score = confidence_score - fatigue_score - time_score - length_pain - quality_flag

    # NOTE: the design doc gives only a QUALITATIVE reading rule here
    # ("rất thấp/âm sâu" = risky, "gần 0 hoặc dương" = ok) — no exact
    # numeric cutoff is specified. This >=0 threshold matches the
    # existing Apps Script's dqNote logic (dataQuality >= 0 ? ổn : cần
    # cân nhắc); revisit if a more precise cutoff is ever defined.
    data_quality_note = (
        "Mẫu tương đối ổn, dùng phân tích được."
        if data_quality_score >= 0
        else "Cần cân nhắc — học sinh có thể mệt hoặc tick bừa."
    )

    return {
        "token": str(response_row[COL_TOKEN] or "").strip(),
        "student_name": str(response_row[COL_NAME] or "").strip(),
        "ux": {
            "score": ux_score,
            "min": UX_MIN,
            "max": UX_MAX,
            "avg": ux_avg,
            "level": ux_level,
            "answers": part_a_answers,
        },
        "quick_select": {
            "most_tired_part": str(response_row[COL_Q15_TIRED] or "").strip(),
            "hardest_part": str(response_row[COL_Q16_HARD] or "").strip(),
            "fatigue_answer": str(response_row[COL_Q17_FATIGUE] or "").strip(),
            "fatigue_score": fatigue_score,
            "time_answer": str(response_row[COL_Q18_TIME] or "").strip(),
            "time_score": time_score,
            "length_answer": str(response_row[COL_Q19_LENGTH] or "").strip(),
            "length_pain": length_pain,
            "quality_flag_answer": str(response_row[COL_Q20_QUALITY] or "").strip(),
            "quality_flag": quality_flag,
            "confidence_answer": str(response_row[COL_Q21_CONFIDENCE] or "").strip(),
            "confidence_score": confidence_score,
        },
        "data_quality_score": data_quality_score,
        "data_quality_note": data_quality_note,
        "open_answers": {
            "q22_confusing_wording": str(response_row[COL_Q22_OPEN] or "").strip(),
            "q23_sensitive": str(response_row[COL_Q23_OPEN] or "").strip(),
            "q25_repetitive": str(response_row[COL_Q25_OPEN] or "").strip(),
            "q26_suggestion": str(response_row[COL_Q26_OPEN] or "").strip(),
            "note": "OpenPainScore / SuggestionQualityScore require manual 0-2 grading by a consultant — not auto-scored.",
        },
    }
