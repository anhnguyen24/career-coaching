from unittest.mock import patch, mock_open


def test_send_results_email():
    """Should call Resend with correct parameters"""
    mock_response = {"id": "email_123"}

    with patch("resend.Emails.send", return_value=mock_response) as mock_send, patch(
        "builtins.open", mock_open(read_data=b"fake file content")
    ):
        from app.services.email import send_results_email

        result = send_results_email(
            to_email="test@example.com",
            name="John",
            personality_type="INTJ",
            pdf_path="/tmp/report.pdf",
            infographic_path="/tmp/infographic.png",
        )

    assert result == {"id": "email_123"}
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["test@example.com"]
    assert "INTJ" in call_args["subject"]
    assert len(call_args["attachments"]) == 2
