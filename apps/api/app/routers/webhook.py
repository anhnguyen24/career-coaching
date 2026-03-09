import hashlib
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.session import get_db
from app.db.models import Submission
from app.models.submission import TallySubmission
from app.services.queue import enqueue_submission

router = APIRouter()


def verify_tally_signature(payload: bytes, signature: str) -> bool:
    if not settings.tally_signing_secret:
        return True
    expected = hmac.new(
        settings.tally_signing_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/tally")
async def tally_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tally_signature: str = Header(default=""),
):
    payload = await request.body()

    if not verify_tally_signature(payload, tally_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()

    try:
        submission = TallySubmission(**data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # Extract email from fields if present
    email = next(
        (f.value for f in submission.fields if "email" in f.label.lower()),
        None,
    )

    # Save to database
    db_submission = Submission(
        event_id=submission.event_id,
        event_type=submission.event_type,
        form_id=submission.form_id,
        respondent_id=submission.respondent_id,
        email=email,
        raw_fields=[f.model_dump() for f in submission.fields],
        status="pending",
    )
    db.add(db_submission)
    await db.flush()

    # Enqueue for AI processing
    await enqueue_submission(submission)

    return {"status": "received", "submission_id": str(db_submission.id)}
