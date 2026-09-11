import smtplib
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import logger


def is_smtp_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_invitation_email(
    recipient_email: str,
    username: str,
    role: str,
    invited_by: str | None = None,
) -> bool:
    settings = get_settings()
    if not is_smtp_configured():
        logger.info(
            "SMTP is not configured, skipping invitation email dispatch",
            recipient=recipient_email,
        )
        return False

    login_url = f"{settings.app_url.rstrip('/')}/login"
    sender = settings.smtp_from or f"Seravops <{settings.smtp_user}>"
    subject = "You've been invited to Seravops"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient_email

    inviter_text = f" by {invited_by}" if invited_by else ""

    # Plaintext fallback
    plain_content = (
        f"Hello {username},\n\n"
        f"You have been invited{inviter_text} to access Seravops with the '{role}' role.\n\n"
        f"You can sign in securely with your Google account ({recipient_email}) by visiting:\n"
        f"{login_url}\n\n"
        "No password is required.\n\n"
        "— The Seravops Team\n"
    )
    msg.set_content(plain_content)

    # Rich HTML content
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      line-height: 1.6;
      color: #1e293b;
      background-color: #f8fafc;
      margin: 0;
      padding: 30px 15px;
    }}
    .container {{
      max-width: 540px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 36px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }}
    .brand {{
      font-size: 22px;
      font-weight: 700;
      color: #0f172a;
      letter-spacing: -0.5px;
      margin-bottom: 20px;
    }}
    .brand span {{
      color: #2563eb;
    }}
    h1 {{
      font-size: 20px;
      font-weight: 600;
      color: #0f172a;
      margin-top: 0;
      margin-bottom: 16px;
    }}
    p {{
      margin: 0 0 16px 0;
      color: #475569;
    }}
    .badge {{
      display: inline-block;
      background: #eff6ff;
      color: #2563eb;
      font-weight: 600;
      font-size: 13px;
      padding: 2px 10px;
      border-radius: 9999px;
      text-transform: capitalize;
    }}
    .btn {{
      display: inline-block;
      background: #2563eb;
      color: #ffffff !important;
      font-weight: 600;
      text-decoration: none;
      padding: 12px 24px;
      border-radius: 8px;
      margin: 20px 0;
    }}
    .footer {{
      margin-top: 28px;
      padding-top: 20px;
      border-top: 1px solid #f1f5f9;
      font-size: 12px;
      color: #94a3b8;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="brand">Sera<span>vops</span></div>
    <h1>You're invited to Seravops</h1>
    <p>Hello <strong>{username}</strong>,</p>
    <p>You have been invited{inviter_text} to access Seravops as a
      <span class="badge">{role}</span>.</p>
    <p>Your account is configured for Google Sign-In with
      <strong>{recipient_email}</strong>. No local password is required.</p>
    <div>
      <a href="{login_url}" class="btn" target="_blank">Sign in with Google &rarr;</a>
    </div>
    <p style="font-size: 13px; color: #64748b;">Or visit:
      <a href="{login_url}" style="color: #2563eb;">{login_url}</a>
    </p>
    <div class="footer">
      This invitation was sent to {recipient_email}.
      If you did not expect this invitation, you can safely ignore this email.
    </div>
  </div>
</body>
</html>"""
    msg.add_alternative(html_content, subtype="html")

    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10.0)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10.0)
            if settings.smtp_use_tls:
                server.starttls()

        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(
            "Successfully sent invitation email",
            recipient=recipient_email,
            role=role,
        )
        return True
    except Exception as exc:
        logger.error(
            "Failed to send invitation email",
            recipient=recipient_email,
            error=str(exc),
        )
        return False
