import resend
from app.config import settings


def send_results_email(
    to_email: str,
    name: str | None,
    personality_type: str,
    pdf_path: str,
    infographic_path: str,
) -> dict:
    resend.api_key = settings.resend_api_key

    with open(pdf_path, "rb") as f:
        pdf_content = f.read()

    with open(infographic_path, "rb") as f:
        infographic_content = f.read()

    recipient_name = name or "there"

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px;">
      <h1 style="color: #1a1a2e; font-size: 24px;">Your Career Coaching Results are Ready! 🎉</h1>
      <p style="color: #444; line-height: 1.7;">Hi {recipient_name},</p>
      <p style="color: #444; line-height: 1.7;">
        Your personality type is <strong style="color: #00e5b0;">{personality_type}</strong>.
      </p>
      <p style="color: #444; line-height: 1.7;">We've attached two files:</p>
      <ul style="color: #444; line-height: 2;">
        <li><strong>Career Coaching Report (PDF)</strong></li>
        <li><strong>Infographic (PNG)</strong></li>
      </ul>
      <div style="background: #f8f9ff; border-left: 4px solid #5b8cff; padding: 16px 20px; margin: 24px 0; border-radius: 0 8px 8px 0;">
        <p style="color: #333; margin: 0; font-size: 14px; line-height: 1.7;">
          Take your time reviewing the results. The action steps in your report are a great starting point.
        </p>
      </div>
      <p style="color: #999; font-size: 12px; margin-top: 40px; border-top: 1px solid #eee; padding-top: 16px;">
        Career Coaching AI · This email was generated automatically.
      </p>
    </div>
    """

    params: resend.Emails.SendParams = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": f"Your Career Coaching Results — {personality_type}",
        "html": html_body,
        "attachments": [
            {
                "filename": "career_report.pdf",
                "content": list(pdf_content),
            },
            {
                "filename": "career_infographic.png",
                "content": list(infographic_content),
            },
        ],
    }

    return resend.Emails.send(params)
