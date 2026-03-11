import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_process_submission_not_found():
    """Should handle missing submission gracefully"""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with patch("anthropic.AsyncAnthropic"):
        from app.services.processor import process_submission

        await process_submission(
            {"event_id": "nonexistent", "fields": []},
            mock_db,
        )
