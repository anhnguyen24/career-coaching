from fastapi import FastAPI
from app.routers import webhook
from app.config import settings

app = FastAPI(
    title="Career Coaching API",
    version="0.1.0",
    debug=settings.debug,
)

app.include_router(webhook.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health():
    return {"status": "ok"}
