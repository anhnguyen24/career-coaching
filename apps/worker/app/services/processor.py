import anthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.services.personality import score_personality
from app.services.career import match_careers
from app.db.models import Submission, Result


async def process_submission(
    submission_data: dict,
    db: AsyncSession,
) -> None:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Find submission in DB
    result = await db.execute(
        select(Submission).where(Submission.event_id == submission_data["event_id"])
    )
    submission = result.scalar_one_or_none()

    if not submission:
        print(f"Submission not found: {submission_data['event_id']}")
        return

    # Update status to processing
    submission.status = "processing"
    await db.flush()

    try:
        # Step 1 — Score personality
        personality = await score_personality(submission_data["fields"], client)

        # Step 2 — Match careers
        careers = await match_careers(personality, client)

        # Step 3 — Save result
        db_result = Result(
            submission_id=submission.id,
            personality_scores=personality,
            career_matches=careers,
            model_version="claude-sonnet-4-20250514",
            status="complete",
        )
        db.add(db_result)

        submission.status = "complete"
        await db.flush()

        print(f"Processed submission {submission.id} successfully")

    except Exception as e:
        submission.status = "failed"
        await db.flush()
        print(f"Failed to process submission {submission.id}: {e}")
        raise
