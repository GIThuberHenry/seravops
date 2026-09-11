from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.services import email_service


def test_is_smtp_configured():
    with patch("app.services.email_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(smtp_host="", smtp_user="", smtp_password="")
        assert not email_service.is_smtp_configured()

        mock_settings.return_value = Settings(
            smtp_host="smtp.gmail.com",
            smtp_user="test@gmail.com",
            smtp_password="password",
        )
        assert email_service.is_smtp_configured()


def test_send_invitation_email_unconfigured():
    with patch("app.services.email_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(smtp_host="", smtp_user="", smtp_password="")
        result = email_service.send_invitation_email("invitee@gmail.com", "Invitee", "developer")
        assert result is False


def test_send_invitation_email_success():
    with (
        patch("app.services.email_service.get_settings") as mock_settings,
        patch("smtplib.SMTP") as mock_smtp_cls,
    ):
        mock_settings.return_value = Settings(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="admin@gmail.com",
            smtp_password="password",
            smtp_from="Seravops <admin@gmail.com>",
            smtp_use_tls=True,
            app_url="http://localhost:7372",
        )
        mock_smtp_instance = MagicMock()
        mock_smtp_cls.return_value = mock_smtp_instance

        result = email_service.send_invitation_email(
            recipient_email="invitee@gmail.com",
            username="alice",
            role="developer",
            invited_by="AdminUser",
        )

        assert result is True
        mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=10.0)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("admin@gmail.com", "password")
        mock_smtp_instance.send_message.assert_called_once()
        mock_smtp_instance.quit.assert_called_once()

        # Check message content
        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "invitee@gmail.com"
        assert sent_msg["Subject"] == "You've been invited to Seravops"


def test_send_invitation_email_smtp_error_handled():
    with (
        patch("app.services.email_service.get_settings") as mock_settings,
        patch("smtplib.SMTP") as mock_smtp_cls,
    ):
        mock_settings.return_value = Settings(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="admin@gmail.com",
            smtp_password="password",
        )
        mock_smtp_cls.side_effect = Exception("Connection timed out")

        result = email_service.send_invitation_email("invitee@gmail.com", "alice", "developer")
        assert result is False
