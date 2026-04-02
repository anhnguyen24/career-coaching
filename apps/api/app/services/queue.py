import json
import redis.asyncio as aioredis
from app.config import settings
from app.models.submission import TallySubmission


async def enqueue_submission(submission: TallySubmission) -> None:
    client = aioredis.from_url(settings.redis_url)
    await client.lpush(
        "submissions:pending",
        json.dumps(
            {
                "event_id": submission.eventId,
                "fields": [f.model_dump() for f in submission.data.fields],
            }
        ),
    )
    await client.close()
