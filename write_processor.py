content = """import json
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.services.personality import score_personality
from app.services.career import match_careers
from app.services.report import generate_pdf
from app.services.infographic import generate_infographic
from app.db.models import Submission, Result


async def process_submission(
    submission_data: dict,
    db: AsyncSession,
) -> dict:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    result = await db.execute(
        select(Submission).where(
            Submission.event_id == submission_data["event_id"]
        )
    )
    submission = result.scalar_one_or_none()

    if not submission:
        print(f"Submission not found: {submission_data[\'event_id\']}")
        return {}

    submission.status = "processing"
    await db.flush()

    try:
        print(f"Scoring personality for {submission.id}...")
        personality = await score_personality(
            submission_data["fields"], client
        )

        print(f"Matching careers for {submission.id}...")
        careers = await match_careers(personality, client)

        db_result = Result(
            submission_id=submission.id,
            personality_scores=personality,
            career_matches=careers,
            model_version="claude-sonnet-4-20250514",
            status="complete",
        )
        db.add(db_result)
        await db.flush()

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

        submission.status = "complete"
        await db.flush()

        print(f"Done! Reports at {pdf_path} and {infographic_path}")

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
        print(f"Failed to process {submission.id}: {e}")
        raise
"""

with open("apps/worker/app/services/processor.py", "w") as f:
    f.write(content)

print("processor.py written successfully!")
