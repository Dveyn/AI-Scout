from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scout.config import get_settings

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    pass


def _tls_context(settings) -> ssl.SSLContext | None:
    if settings.smtp_tls_reject_unauthorized:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def send_email_sync(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_user:
        raise EmailSendError("SMTP не настроен: задайте SMTP_HOST и SMTP_USER в scout/.env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email or settings.smtp_user}>"
    msg["To"] = to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    tls_ctx = _tls_context(settings)

    try:
        if settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=30, context=tls_ctx
            )
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
            if settings.smtp_use_tls:
                server.starttls(context=tls_ctx)

        if settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email or settings.smtp_user, [to], msg.as_string())
        server.quit()
    except Exception as exc:
        logger.exception("SMTP send failed to %s", to)
        raise EmailSendError(str(exc)) from exc


async def send_email(to: str, subject: str, body: str) -> None:
    import asyncio

    await asyncio.to_thread(send_email_sync, to, subject, body)
