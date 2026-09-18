"""Envío del correo de confirmación por SMTP.

Pensado para el Postfix de la instancia (postfix.service escuchando en localhost:25,
sin autenticación ni TLS). Postfix acepta el mensaje al instante y lo entrega/reenvía
(relayhost) por su cuenta; si Postfix está caído, aquí se lanza MailError.
No se usa POP ni la API de Gmail.
"""
import html
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

log = logging.getLogger(__name__)


class MailError(Exception):
    """No se pudo entregar el mensaje al servidor SMTP local."""


class SmtpMailer:
    def __init__(self, settings):
        self.s = settings

    def build_verification(self, to_email, nombre, link, ttl_hours):
        msg = EmailMessage()
        msg["Subject"] = "Confirma tu cuenta de Library"
        msg["From"] = self.s.mail_from
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        domain = parseaddr(self.s.mail_from)[1].rpartition("@")[2] or "localhost"
        msg["Message-ID"] = make_msgid(domain=domain)
        token = link.rsplit("/", 1)[-1]  # el mismo token del enlace, visible para poder probar a mano
        msg.set_content(
            f"Hola {nombre},\n\n"
            "Da clic aquí para confirmar tu cuenta:\n\n"
            f"{link}\n\n"
            f"Si el enlace no abre, tu token de confirmación es:\n{token}\n"
            "(úsalo en GET /verify/<token>)\n\n"
            f"Vale por {ttl_hours} horas. Si no fuiste tú, ignora este mensaje.\n"
        )
        msg.add_alternative(
            '<p>Hola {nombre},</p>'
            '<p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#1f4e79;color:#ffffff;'
            'text-decoration:none;border-radius:6px;font-weight:bold">Da clic aquí para confirmar tu cuenta</a></p>'
            '<p style="color:#555;font-size:13px">Si el botón no abre, copia este enlace en tu navegador:<br>'
            '<a href="{link}">{link}</a></p>'
            '<p style="color:#555;font-size:13px">Token de confirmación (para probar a mano): <code>{token}</code></p>'
            '<p style="color:#888;font-size:12px">Vale por {ttl} horas. Si no fuiste tú, ignora este mensaje.</p>'.format(
                nombre=html.escape(nombre), link=html.escape(link, quote=True), token=html.escape(token), ttl=int(ttl_hours)),
            subtype="html",
        )
        return msg

    def send_verification(self, to_email, nombre, link, ttl_hours):
        msg = self.build_verification(to_email, nombre, link, ttl_hours)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=self.s.smtp_timeout) as smtp:
                smtp.ehlo()
                if self.s.smtp_starttls:
                    smtp.starttls()
                    smtp.ehlo()
                if self.s.smtp_username:
                    smtp.login(self.s.smtp_username, self.s.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            log.error("No se pudo entregar el correo a %s:%s (%s: %s)", self.s.smtp_host, self.s.smtp_port,
                      type(exc).__name__, exc)
            raise MailError(str(exc)) from exc
