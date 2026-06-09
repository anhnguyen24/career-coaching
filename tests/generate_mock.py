"""
src/tests/generate_mock.py — Generate anonymised mock submission for integration testing

Generates a deterministic set of random answers, runs scorer.py to compute
expected scores, and saves everything to mock_submission.json.

Run whenever the survey version changes:
    python src/tests/generate_mock.py src/survey_versions/survey_v2.json

Output:
    src/tests/mock_submission.json
"""

import json
import random
import sys
from pathlib import Path

# Allow import from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "scorer"))

from scorer import Scorer

# ============================================================
# Config
# ============================================================

OUTPUT_FILE = Path(__file__).parent / "mock_submission.json"

# Deterministic seed so answers are always the same for a given version
# Change this if you want a different set of answers
RANDOM_SEED = 42

# Scale min/max (must match survey metadata)
SCALE_MIN = 1
SCALE_MAX = 5

# Mock student info — fully anonymised
MOCK_STUDENT_INFO = {
    "name":          "Integration Test",
    "token":         "HN-2026-0009",
    "dob":           "01/01/2000",
    "gender":        "Khác",
    "grade":         "12",
    "school_year":   "2025-2026",
    "school":        "TEST_SCHOOL",
    "city":          "TEST_CITY",
    "email":         "test@test.internal",
    "phone":         "0000000000",
    "direction":     "TEST",
    "after_school":  "TEST",
    "fav_subjects":  "TEST",
    "fav_activities":"TEST",
    "commitment":    "Đồng ý",
}


# ============================================================
# Main
# ============================================================

def generate_mock(survey_path: Path) -> dict:
    """Generate mock answers and compute expected scores."""

    with open(survey_path, encoding="utf-8") as f:
        survey = json.load(f)

    version         = survey["version"]
    total_questions = survey["metadata"]["total_questions"]

    # Generate deterministic random answers
    rng = random.Random(f"{RANDOM_SEED}-{version}")
    answers: dict[int, int] = {
        i: rng.randint(SCALE_MIN, SCALE_MAX)
        for i in range(1, total_questions + 1)
    }

    # Run scorer to get expected results
    scorer  = Scorer(survey)
    result  = scorer.score(answers)
    result_dict = result.to_dict()

    # Build mock submission
    mock = {
        "_comment": (
            f"Auto-generated mock submission for survey {version}. "
            f"Do not edit manually — regenerate with generate_mock.py."
        ),
        "version":      version,
        "student_info": MOCK_STUDENT_INFO,
        "answers":      answers,
        "expected":     result_dict,
    }

    return mock


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/tests/generate_mock.py src/survey_versions/survey_v2.json")
        sys.exit(1)

    survey_path = Path(sys.argv[1])
    if not survey_path.exists():
        print(f"❌ File not found: {survey_path}")
        sys.exit(1)

    print(f"Generating mock submission from {survey_path.name}...")
    mock = generate_mock(survey_path)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(mock, f, ensure_ascii=False, indent=2)

    version = mock["version"]
    total   = len(mock["answers"])
    mbti    = mock["expected"].get("mbti", {}).get("type", "?")
    top3    = mock["expected"].get("holland", {}).get("top3_label", "?")
    sss     = next(
        (cs["score"] for cs in mock["expected"].get("composite_scores", []) if cs["id"] == "sss"),
        "?"
    )

    print(f"✅ Mock generated: {OUTPUT_FILE}")
    print(f"   Version:  {version}")
    print(f"   Answers:  {total} questions")
    print(f"   MBTI:     {mbti}")
    print(f"   Holland:  {top3}")
    print(f"   SSS:      {sss}")
    print(f"\nCommit this file when done:")
    print(f"   git add {OUTPUT_FILE}")
    print(f"   git commit -m 'chore: regenerate mock for {version}'")


if __name__ == "__main__":
    main()
