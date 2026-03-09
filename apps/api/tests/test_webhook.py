from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db

client = TestClient(app)


async def mock_get_db():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    yield mock_db


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_invalid_payload():
    """Empty payload should return 422 validation error"""
    response = client.post("/webhooks/tally", json={})
    assert response.status_code == 422


def test_webhook_valid_payload():
    """Valid payload should return 200, DB and Redis are mocked"""
    payload = {
        "event_id": "evt_123",
        "event_type": "FORM_RESPONSE",
        "form_id": "form_abc",
        "respondent_id": "resp_xyz",
        "fields": [{"key": "q1", "label": "What is your name?", "value": "John"}],
    }

    app.dependency_overrides[get_db] = mock_get_db

    with patch("app.routers.webhook.enqueue_submission", new_callable=AsyncMock):
        response = client.post("/webhooks/tally", json=payload)

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert "submission_id" in response.json()
