# ruff: noqa: E402
import sys
from pathlib import Path
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Add shared packages to path
_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str((_root / "../packages").resolve()))
sys.path.insert(0, str(_root))

from app.config import settings
from app.services.personality import score_personality
from app.services.career import match_careers
from mailer.app.services.email import send_results_email
from reports.report import generate_pdf
from reports.infographic import generate_infographic
from app.db.models import Submission, Result


def get_mock_results() -> tuple[dict, dict]:
    personality = {
        "mbti": "INTJ",
        "big_five": {
            "openness": 0.85,
            "conscientiousness": 0.75,
            "extraversion": 0.30,
            "agreeableness": 0.60,
            "neuroticism": 0.25,
        },
        "strengths": ["Strategic thinking", "Problem solving", "Independence"],
        "blind_spots": ["Perfectionism", "Difficulty delegating"],
        "summary": "A strategic and analytical thinker who excels at complex problem solving and long-term planning.",
    }
    careers = {
        "careers": [
            {
                "title": "Software Architect",
                "fit_score": 0.92,
                "reason": "Matches analytical nature and systems thinking",
                "required_skills": ["Python", "System Design", "Leadership"],
                "growth_outlook": "positive",
            },
            {
                "title": "Data Scientist",
                "fit_score": 0.88,
                "reason": "Leverages analytical strengths and curiosity",
                "required_skills": ["Python", "Statistics", "ML"],
                "growth_outlook": "positive",
            },
            {
                "title": "Product Manager",
                "fit_score": 0.75,
                "reason": "Strategic vision suits product leadership",
                "required_skills": ["Communication", "Analytics", "Roadmapping"],
                "growth_outlook": "stable",
            },
        ],
        "action_steps": [
            "Build a portfolio of 3 projects showcasing your technical skills",
            "Get certified in your primary technology stack",
            "Start contributing to open source projects",
        ],
    }
    return personality, careers


async def process_submission(
    submission_data: dict,
    db: AsyncSession,
) -> dict:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Find submission in DB
    result = await db.execute(
        select(Submission).where(Submission.event_id == submission_data["event_id"])
    )
    submission = result.scalar_one_or_none()

    if not submission:
        print(f"Submission not found: {submission_data['event_id']}")
        return {}

    # Update status to processing
    submission.status = "processing"
    await db.flush()

    try:
        if settings.mock_ai:
            print(f"Using mock AI for {submission.id}...")
            personality, careers = get_mock_results()
        else:
            print(f"Scoring personality for {submission.id}...")
            personality = await score_personality(submission_data["fields"], client)
            print(f"Matching careers for {submission.id}...")
            careers = await match_careers(personality, client)

        # Step 3 — Save result to DB
        db_result = Result(
            submission_id=submission.id,
            personality_scores=personality,
            career_matches=careers,
            model_version="claude-sonnet-4-20250514",
            status="complete",
        )
        db.add(db_result)
        await db.flush()

        # Step 4 — Generate reports
        print(f"Generating reports for {submission.id}...")
        result_data = {
            "name": submission.email,
            "personality_scores": personality,
            "career_matches": careers,
        }

        pdf_path = generate_pdf(
            result_data,
            f"{submission.id}_report.pdf",
        )

        infographic_path = await generate_infographic(
            result_data,
            f"{submission.id}_infographic.png",
        )

        # Step 5 — Update submission status
        submission.status = "complete"
        await db.flush()

        print(f"Done! Reports at {pdf_path} and {infographic_path}")

        # Step 6 — Send email
        if submission.email:
            print(f"Sending email to {submission.email}...")
            send_results_email(
                to_email=submission.email,
                name=submission.email,
                personality_type=personality["mbti"],
                pdf_path=pdf_path,
                infographic_path=infographic_path,
            )
            submission.status = "delivered"
        else:
            submission.status = "complete"

        await db.flush()

        return {
            "submission_id": str(submission.id),
            "pdf_path": pdf_path,
            "infographic_path": infographic_path,
            "personality": personality,
            "careers": careers,
        }

    except Exception as e:
        submission.status = "failed"
        await db.flush()
        print(f"Failed to process submission {submission.id}: {e}")
        raise
