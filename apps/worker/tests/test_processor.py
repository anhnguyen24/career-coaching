import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.processor import process_submission


@pytest.mark.asyncio
async def test_process_submission_not_found():
    """Should handle missing submission gracefully"""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with patch("app.services.processor.anthropic.AsyncAnthropic"):
        from app.services.processor import process_submission

        result = await process_submission(
            {"event_id": "nonexistent", "fields": []},
            mock_db,
        )

    assert result == {}


@pytest.mark.asyncio
async def test_process_submission_success():
    """Should process submission and return report paths"""
    mock_submission = MagicMock()
    mock_submission.id = "test-uuid-123"
    mock_submission.email = "test@example.com"
    mock_submission.status = "pending"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_submission)
        )
    )

    mock_personality = {
        "mbti": "INTJ",
        "big_five": {
            "openness": 0.85,
            "conscientiousness": 0.75,
            "extraversion": 0.30,
            "agreeableness": 0.60,
            "neuroticism": 0.25,
        },
        "strengths": ["Strategic thinking"],
        "blind_spots": ["Perfectionism"],
        "summary": "A strategic thinker.",
    }

    mock_careers = {
        "careers": [
            {
                "title": "Software Architect",
                "fit_score": 0.92,
                "reason": "Matches analytical nature",
                "required_skills": ["Python"],
                "growth_outlook": "positive",
            }
        ],
        "action_steps": ["Build portfolio"],
    }

    with patch(
        "app.services.processor.score_personality",
        new_callable=AsyncMock,
        return_value=mock_personality,
    ), patch(
        "app.services.processor.match_careers",
        new_callable=AsyncMock,
        return_value=mock_careers,
    ), patch(
        "app.services.processor.generate_pdf", return_value="/tmp/test_report.pdf"
    ), patch(
        "app.services.processor.generate_infographic",
        new_callable=AsyncMock,
        return_value="/tmp/test_infographic.png",
    ), patch(
        "app.services.processor.send_results_email", return_value={"id": "email_123"}
    ), patch("app.services.processor.anthropic.AsyncAnthropic"):
        result = await process_submission(
            {"event_id": "evt_123", "fields": []},
            mock_db,
        )

    assert result["pdf_path"] == "/tmp/test_report.pdf"
    assert result["infographic_path"] == "/tmp/test_infographic.png"
    assert result["personality"]["mbti"] == "INTJ"
