"""
server/routers/health.py — Health check endpoint
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "career-coaching-api"}
