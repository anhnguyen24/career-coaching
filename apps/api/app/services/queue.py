import json
import redis.asyncio as aioredis
from app.config import settings
from app.models.submission import TallySubmission


async def enqueue_submission(submission: TallySubmission) -> None:
    client = aioredis.from_url(settings.redis_url)
    await client.lpush(
        "submissions:pending",
        json.dumps(submission.model_dump()),
    )
    await client.aclose()
