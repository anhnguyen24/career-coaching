"""
server/main.py — Career Coaching FastAPI server

Endpoints:
    GET  /health          → health check
    POST /webhook/score   → score a survey submission
"""

from fastapi import FastAPI
from routers import health, webhook

app = FastAPI(
    title="Career Coaching API",
    description="Scoring and report generation for the GenZ career coaching platform",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(webhook.router, prefix="/webhook")
