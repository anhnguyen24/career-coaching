from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_invalid_payload():
    """Empty payload should return 422 validation error"""
    response = client.post("/webhooks/tally", json={})
    assert response.status_code == 422


def test_webhook_valid_payload():
    """Valid payload should return 200, Redis is mocked"""
    payload = {
        "event_id": "evt_123",
        "event_type": "FORM_RESPONSE",
        "form_id": "form_abc",
        "respondent_id": "resp_xyz",
        "fields": [{"key": "q1", "label": "What is your name?", "value": "John"}],
    }
    with patch(
        "app.routers.webhook.enqueue_submission",
        new_callable=AsyncMock,
    ):
        response = client.post("/webhooks/tally", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "received"}
