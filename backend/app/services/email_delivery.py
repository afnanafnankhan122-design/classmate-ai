from email.message import EmailMessage
from email.utils import formataddr
from html import escape
import logging
import smtplib
import ssl

from app.core.config import settings

logger = logging.getLogger(__name__)
PASSWORD_RESET_EXPIRATION_MINUTES = 30


def _send(message: EmailMessage) -> None:
    if not settings.smtp_configured:
        raise RuntimeError("SMTP password-recovery delivery is not configured.")

    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
                context=ssl.create_default_context(),
            ) as client:
                client.login(settings.smtp_username, settings.smtp_password)
                refused = client.send_message(message)
        else:
            with smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            ) as client:
                client.ehlo()
                if settings.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                client.login(settings.smtp_username, settings.smtp_password)
                refused = client.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("SMTP email delivery failed (error_type=%s)", type(exc).__name__)
        raise


def send_password_reset_email(
    recipient: str,
    reset_url: str,
    expiration_minutes: int = PASSWORD_RESET_EXPIRATION_MINUTES,
) -> None:
    message = EmailMessage()
    message["Subject"] = "Reset your ClassMate AI password"
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = recipient
    message.set_content(
        "We received a request to reset your ClassMate AI password.\n\n"
        f"Use this link to choose a new password: {reset_url}\n\n"
        f"This link expires in {expiration_minutes} minutes and can only be used once. "
        "If you did not request a reset, you can ignore this email. Your password will not "
        "change unless you use the link.\n\n"
        "ClassMate AI"
    )
    message.add_alternative(
        "<p>We received a request to reset your ClassMate AI password.</p>"
        f'<p><a href="{escape(reset_url, quote=True)}">Choose a new password</a></p>'
        f"<p>This link expires in {expiration_minutes} minutes and can only be used once. "
        "If you did not request a reset, you can ignore this email. Your password will not "
        "change unless you use the link.</p><p>ClassMate AI</p>",
        subtype="html",
    )
    _send(message)


def send_password_changed_email(recipient: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Your ClassMate AI password was changed"
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = recipient
    message.set_content(
        "Your ClassMate AI account password was successfully changed.\n\n"
        "If you did not make this change, contact ClassMate AI support immediately.\n\n"
        "ClassMate AI"
    )
    message.add_alternative(
        "<p>Your ClassMate AI account password was successfully changed.</p>"
        "<p>If you did not make this change, contact ClassMate AI support immediately.</p>"
        "<p>ClassMate AI</p>",
        subtype="html",
    )
    _send(message)
