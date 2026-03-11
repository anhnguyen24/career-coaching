import asyncio
import json
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.services.processor import process_submission


async def get_db_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()


async def run_worker():
    print("Worker started, listening for jobs...")
    redis_client = aioredis.from_url(settings.redis_url)

    while True:
        try:
            # Block and wait for next job (timeout 1s to allow clean shutdown)
            job = await redis_client.brpop("submissions:pending", timeout=1)

            if job is None:
                continue

            _, data = job
            submission_data = json.loads(data)
            print(f"Processing submission: {submission_data['event_id']}")

            async with await get_db_session() as db:
                async with db.begin():
                    await process_submission(submission_data, db)

        except Exception as e:
            print(f"Worker error: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
