"""
deploy.py — Survey deployment orchestrator

Usage:
    python src/deploy.py src/survey_versions/survey_v2.json           # run all steps
    python src/deploy.py src/survey_versions/survey_v2.json --form    # only update Google Form questions
    python src/deploy.py src/survey_versions/survey_v2.json --scorer  # inject permanent seed row + integration test
    python src/deploy.py src/survey_versions/survey_v2.json --test    # integration test only (no permanent changes)

Step summary:
    --form    → validate + update Google Form questions (permanent)
    --scorer  → validate + inject mock row + compare + keep if passed (permanent seed row)
    --test    → validate + inject mock row + compare + delete regardless (nothing permanent)
    no flags  → --form + --scorer + --test (all steps)

Requirements:
    pip install google-auth google-auth-oauthlib google-api-python-client jsonschema python-dotenv

Environment variables (or .env file):
    GOOGLE_SERVICE_ACCOUNT_JSON   path to service account credentials JSON file
    GOOGLE_FORM_ID                main survey Google Form ID
    GOOGLE_SHEET_ID               Form Responses 2 spreadsheet ID
    SCORES_SHEET_NAME             name of the Scores tab (default: Scores)
    RESPONSE_SHEET_NAME           name of the response tab (default: Form Responses 2)
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from jsonschema import validate, ValidationError

load_dotenv()

# ============================================================
# Paths
# ============================================================
SRC_DIR     = Path(__file__).parent
SCHEMA_FILE = SRC_DIR / "survey_schema.json"


# ============================================================
# Validation
# ============================================================

def validate_survey(survey_path: Path) -> dict:
    """Load and validate survey JSON against the schema."""
    print(f"\n{'='*60}")
    print(f"  STEP 1 — Validating {survey_path.name}")
    print(f"{'='*60}")

    with open(survey_path, encoding="utf-8") as f:
        survey = json.load(f)

    with open(SCHEMA_FILE, encoding="utf-8") as f:
        schema = json.load(f)

    try:
        validate(instance=survey, schema=schema)
        print(f"  ✅ Schema validation passed")
    except ValidationError as e:
        print(f"  ❌ Schema validation failed: {e.message}")
        print(f"     Path: {' → '.join(str(p) for p in e.absolute_path)}")
        sys.exit(1)

    # Extra checks
    total_questions = sum(len(t["questions"]) for t in survey["tests"])
    expected = survey["metadata"]["total_questions"]
    if total_questions != expected:
        print(f"  ❌ Question count mismatch: expected {expected}, got {total_questions}")
        sys.exit(1)

    numbers = sorted(q["number"] for t in survey["tests"] for q in t["questions"])
    if numbers != list(range(1, total_questions + 1)):
        print(f"  ❌ Question numbers are not sequential 1–{total_questions}")
        sys.exit(1)

    print(f"  ✅ {total_questions} questions, sequential numbering verified")
    print(f"  ✅ Version: {survey['version']}")
    return survey


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Deploy survey to Google Form and Scores tab")
    parser.add_argument("survey_file", help="Path to survey JSON file")
    parser.add_argument("--form",       action="store_true", help="Only update Google Form questions")
    parser.add_argument("--scorer",     action="store_true", help="Inject permanent seed row + integration test")
    parser.add_argument("--test",       action="store_true", help="Integration test only — no permanent changes")
    parser.add_argument("--check-form", action="store_true", help="Read-only: compare live form vs JSON, no changes")
    args = parser.parse_args()

    survey_path = Path(args.survey_file)
    if not survey_path.exists():
        print(f"❌ File not found: {survey_path}")
        sys.exit(1)

    # Determine which steps to run
    # --check-form is a standalone read-only operation
    if args.check_form:
        survey = validate_survey(survey_path)

        print(f"\n{'='*60}")
        print(f"  CHECK — Comparing live Google Form vs {survey_path.name}")
        print(f"{'='*60}")
        from form.form_deployer import FormDeployer
        deployer = FormDeployer(survey)
        in_sync = deployer.check()
        sys.exit(0 if in_sync else 1)

    run_all    = not (args.form or args.scorer or args.test)
    run_form   = run_all or args.form
    run_scorer = run_all or args.scorer
    run_test   = run_all or args.test

    print(f"\n🚀 Career Coaching Survey Deploy")
    print(f"   File:    {survey_path}")
    print(f"   Steps:   {'form ' if run_form else ''}{'scorer ' if run_scorer else ''}{'test' if run_test else ''}")

    # Step 1 — Validate
    survey = validate_survey(survey_path)

    # Step 2 — Deploy form questions
    if run_form:
        print(f"\n{'='*60}")
        print(f"  STEP 2 — Deploying Google Form questions")
        print(f"{'='*60}")
        from form.form_deployer import FormDeployer
        deployer = FormDeployer(survey)
        deployer.deploy()

    # Step 3 — Deploy scorer (permanent seed row + integration test)
    if run_scorer:
        print(f"\n{'='*60}")
        print(f"  STEP 3 — Deploying Scores tab seed row")
        print(f"{'='*60}")
        from scorer.scorer_deployer import ScorerDeployer
        scorer_deployer = ScorerDeployer(survey)
        scorer_deployer.deploy_formulas()

    # Step 4 — Integration test only (no permanent changes)
    if run_test:
        print(f"\n{'='*60}")
        print(f"  STEP 4 — Running integration test (temporary)")
        print(f"{'='*60}")
        if not run_scorer:
            from scorer.scorer_deployer import ScorerDeployer
            scorer_deployer = ScorerDeployer(survey)
        scorer_deployer.run_integration_test()

    print(f"\n{'='*60}")
    print(f"  ✅ Deploy complete — version {survey['version']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
