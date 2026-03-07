import hashlib
import hmac
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError
from app.config import settings
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

    await enqueue_submission(submission)

    return {"status": "received"}
