"""Confirmación del correo por enlace, enviado por el Postfix de la instancia."""
import hashlib
import json
import smtplib
from datetime import timedelta
from xml.etree import ElementTree as ET

import pytest

from login_service import ConfigError, Settings
from login_service.mailer import MailError, SmtpMailer

PERSON = {"nombre": "Ana", "apellido_paterno": "López", "apellido_materno": "Díaz",
          "email": "ana@gmail.com", "password": "ClaveSegura123"}


def js(r):
    return json.loads(r.get_data(as_text=True))


def register(client, **over):
    return client.post("/register?format=json", json=dict(PERSON, **over))


def do_login(client, fmt="json"):
    return client.post(f"/login?format={fmt}", json={"email": PERSON["email"], "password": PERSON["password"]})


# --------------------------------------------------------------- registro
def test_register_sends_one_email_with_the_link(cm_client, mailer):
    r = register(cm_client)
    body = js(r)
    assert r.status_code == 201 and body["verification_email"] == "sent" and body["user"]["email_verified"] is False
    assert "correo" in body["message"] and "POST /login" in body["message"]
    (mail,) = mailer.sent
    assert mail["to"] == "ana@gmail.com" and mail["nombre"] == "Ana" and mail["ttl_hours"] == 24
    assert mail["link"].startswith("http://vm.example:5000/verify/") and len(mail["link"].rsplit("/", 1)[1]) >= 40


def test_only_the_hash_of_the_token_is_stored(cm_client, repo, mailer):
    register(cm_client)
    token = mailer.last_token
    (v,) = repo.verifications
    assert v["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in json.dumps(v, default=str)
    assert v["expires_at"] - v["created_at"] == timedelta(hours=24)


def test_register_xml_says_what_to_do_next(cm_client):
    r = cm_client.post("/register", json=PERSON)
    root = ET.fromstring(r.get_data())
    assert r.status_code == 201 and root.findtext("verification_email") == "sent"
    assert "enlace de confirmación" in root.findtext("message")


def test_mail_failure_keeps_the_account_and_tells_the_user(cm_client, repo, mailer):
    mailer.fail = True
    r = register(cm_client)
    body = js(r)
    assert r.status_code == 201 and body["verification_email"] == "failed" and "resend-verification" in body["message"]
    assert "ana@gmail.com" in repo.users                       # la cuenta sí se creó
    assert register(cm_client).status_code == 409              # y reintentar el registro no es el camino


def test_register_never_touches_mailer_when_validation_fails(cm_client, mailer):
    assert register(cm_client, email="no-es-correo").status_code == 400
    assert cm_client.post("/register?format=json", json=dict(PERSON, email="dup@gmail.com")).status_code == 201
    assert cm_client.post("/register?format=json", json=dict(PERSON, email="DUP@gmail.com")).status_code == 409
    assert [m["to"] for m in mailer.sent] == ["dup@gmail.com"]


# ------------------------------------------------------------------ login
def test_login_blocked_until_confirmed(cm_client, mailer):
    register(cm_client)
    r = do_login(cm_client)
    assert r.status_code == 403 and js(r)["error"]["code"] == "email_not_confirmed"
    assert "resend-verification" in js(r)["error"]["message"] and cm_client.get_cookie("login_session") is None
    assert cm_client.get(f"/verify/{mailer.last_token}?format=json").status_code == 200
    ok = do_login(cm_client)
    assert ok.status_code == 200 and js(ok)["user"]["email_verified"] is True


def test_wrong_password_is_401_even_when_unconfirmed(cm_client):
    register(cm_client)
    r = cm_client.post("/login?format=json", json={"email": PERSON["email"], "password": "incorrecta"})
    assert r.status_code == 401                                 # no revela que la cuenta existe sin confirmar


def test_monolith_accounts_are_already_verified(cm_client, repo):
    import bcrypt
    from datetime import datetime, timezone
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)
    repo.users["admin@example.com"] = dict(
        user_id=7, nombre=None, apellido_paterno=None, apellido_materno=None, display_name="Administrador",
        email="admin@example.com", is_active=True, created_at=when, email_verified_at=when,
        password_hash=bcrypt.hashpw(b"CambieEstaClave123!", bcrypt.gensalt(4)).decode())
    r = cm_client.post("/login?format=json", json={"email": "admin@example.com", "password": "CambieEstaClave123!"})
    assert r.status_code == 200


# ----------------------------------------------------------------- verify
def test_verify_default_xml_then_idempotent(cm_client, mailer, repo):
    register(cm_client)
    r = cm_client.get(f"/verify/{mailer.last_token}")
    root = ET.fromstring(r.get_data())
    assert r.status_code == 200 and r.mimetype == "application/xml"
    assert root.findtext("status") == "confirmed" and "Cuenta confirmada" in root.findtext("message")
    assert root.findtext("user/email_verified") == "true" and repo.users["ana@gmail.com"]["email_verified_at"]
    again = js(cm_client.get(f"/verify/{mailer.last_token}?format=json"))     # p. ej. el escáner de Gmail ya lo abrió
    assert again["status"] == "already_confirmed" and "ya estaba confirmada" in again["message"]


@pytest.mark.parametrize("token", ["corto", "x" * 43, "a b" * 20, "%2e%2e%2f" * 5, "a" * 101])
def test_verify_rejects_unknown_or_malformed_tokens(cm_client, token):
    register(cm_client)
    r = cm_client.get(f"/verify/{token}?format=json")
    # Con barras codificadas (%2f) ni siquiera coincide con la ruta: sigue siendo un 404 sin tocar la BD.
    assert r.status_code == 404 and js(r)["error"]["code"] in ("invalid_token", "not_found")


def test_verify_expired_token_is_410_and_account_stays_unconfirmed(cm_client, mailer, clock, repo):
    register(cm_client)
    clock.advance(hours=24, seconds=1)
    r = cm_client.get(f"/verify/{mailer.last_token}?format=json")
    assert r.status_code == 410 and js(r)["error"]["code"] == "token_expired"
    assert repo.users["ana@gmail.com"]["email_verified_at"] is None and do_login(cm_client).status_code == 403


def test_token_valid_until_the_last_second(cm_client, mailer, clock):
    register(cm_client)
    clock.advance(hours=23, minutes=59, seconds=59)
    assert cm_client.get(f"/verify/{mailer.last_token}?format=json").status_code == 200


# ----------------------------------------------------------------- resend
def test_resend_flow_after_expiry(cm_client, mailer, clock):
    register(cm_client)
    clock.advance(hours=25)
    r = cm_client.post("/resend-verification?format=json", json={"email": "ANA@gmail.com"})
    assert r.status_code == 202 and len(mailer.sent) == 2
    assert cm_client.get(f"/verify/{mailer.last_token}?format=json").status_code == 200
    assert do_login(cm_client).status_code == 200


def test_resend_has_a_cooldown(cm_client, mailer, clock):
    register(cm_client)
    for _ in range(3):
        assert cm_client.post("/resend-verification?format=json", json={"email": PERSON["email"]}).status_code == 202
    assert len(mailer.sent) == 1                                # nada dentro de los primeros 60 s
    clock.advance(seconds=60)
    cm_client.post("/resend-verification?format=json", json={"email": PERSON["email"]})
    assert len(mailer.sent) == 2


def test_resend_answers_the_same_for_unknown_confirmed_and_pending(cm_client, mailer, clock):
    register(cm_client)
    clock.advance(minutes=5)
    unknown = cm_client.post("/resend-verification?format=json", json={"email": "nadie@gmail.com"})
    pending = cm_client.post("/resend-verification?format=json", json={"email": PERSON["email"]})
    cm_client.get(f"/verify/{mailer.last_token}?format=json")
    confirmed = cm_client.post("/resend-verification?format=json", json={"email": PERSON["email"]})
    assert unknown.status_code == pending.status_code == confirmed.status_code == 202
    assert js(unknown) == js(pending) == js(confirmed)
    assert [m["to"] for m in mailer.sent] == ["ana@gmail.com", "ana@gmail.com"]   # solo el registro y el reenvío pendiente


def test_resend_requires_email(cm_client):
    assert cm_client.post("/resend-verification?format=json", json={}).status_code == 400
    assert cm_client.post("/resend-verification").status_code == 400          # sin cuerpo


def test_resend_does_not_send_when_mail_is_down_but_still_202(cm_client, mailer, clock):
    register(cm_client)
    clock.advance(minutes=5)
    mailer.fail = True
    assert cm_client.post("/resend-verification?format=json", json={"email": PERSON["email"]}).status_code == 202


# ------------------------------------------- confirmación desactivada (dev)
def test_confirmation_disabled_registers_active_accounts_without_email(client, mailer):
    r = client.post("/register?format=json", json=PERSON)
    assert js(r)["verification_email"] == "not_required" and mailer.sent == []
    assert client.post("/login?format=json", json={"email": PERSON["email"], "password": PERSON["password"]}).status_code == 200
    assert client.post("/resend-verification?format=json", json={"email": PERSON["email"]}).status_code == 202
    assert mailer.sent == []


# ------------------------------------------------------ SmtpMailer (Postfix)
class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout, self.calls, self.msg = host, port, timeout, [], None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.msg = msg


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_smtp_mailer_talks_plain_smtp_to_local_postfix(cm_settings, smtp):
    SmtpMailer(cm_settings).send_verification("ana@gmail.com", "Ana", "http://vm.example:5000/verify/TOKEN", 24)
    (conn,) = smtp.instances
    assert (conn.host, conn.port, conn.timeout) == ("localhost", 25, 10)
    assert conn.calls == ["ehlo"]                               # sin STARTTLS ni login contra Postfix local
    msg = conn.msg
    assert msg["To"] == "ana@gmail.com" and msg["From"] == "Library <no-reply@example.com>"
    assert msg["Subject"] == "Confirma tu cuenta de Library" and msg["Message-ID"].endswith("@example.com>")
    text = msg.get_body(preferencelist=("plain",)).get_content()
    page = msg.get_body(preferencelist=("html",)).get_content()
    assert msg.get_content_type() == "multipart/alternative"
    assert "Da clic aquí para confirmar tu cuenta" in text and "http://vm.example:5000/verify/TOKEN" in text
    assert "TOKEN" in text.split("token de confirmación es:")[1] and "Hola Ana" in text and "24 horas" in text
    assert '<a href="http://vm.example:5000/verify/TOKEN"' in page and "Da clic aquí para confirmar tu cuenta</a>" in page
    assert "<code>TOKEN</code>" in page


def test_smtp_mailer_html_escapes_the_name_and_link(cm_settings):
    msg = SmtpMailer(cm_settings).build_verification("a@gmail.com", "<script>alert(1)</script>", 'http://x/verify/T"><b>', 24)
    page = msg.get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in page and "&lt;script&gt;" in page and '"><b>' not in page


def test_smtp_mailer_uses_starttls_and_auth_only_when_configured(cm_settings, smtp):
    from dataclasses import replace
    s = replace(cm_settings, smtp_host="smtp.relay.test", smtp_port=587, smtp_starttls=True, smtp_username="u", smtp_password="p")
    SmtpMailer(s).send_verification("ana@gmail.com", "Ana", "http://x/verify/T", 24)
    assert smtp.instances[0].calls == ["ehlo", "starttls", "ehlo", ("login", "u")]


def test_smtp_mailer_wraps_connection_errors(cm_settings, monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError("postfix.service detenido")
    monkeypatch.setattr(smtplib, "SMTP", boom)
    with pytest.raises(MailError):
        SmtpMailer(cm_settings).send_verification("ana@gmail.com", "Ana", "http://x/verify/T", 24)


def test_smtp_mailer_rejects_header_injection(cm_settings, smtp):
    with pytest.raises(ValueError):
        SmtpMailer(cm_settings).build_verification("a@gmail.com\nBcc: victima@x.com", "Ana", "http://x", 24)


# ----------------------------------------------------------------- config
def test_config_requires_mail_from_when_confirmation_is_on():
    with pytest.raises(ConfigError, match="MAIL_FROM"):
        Settings(secret_key="x" * 20, database_url="postgresql://x", email_confirmation_required=True).validate()
    Settings(secret_key="x" * 20, database_url="postgresql://x", email_confirmation_required=False).validate()
    with pytest.raises(ConfigError, match="PUBLIC_BASE_URL"):
        Settings(secret_key="x" * 20, database_url="postgresql://x", mail_from="a@b.co", public_base_url="vm:5000").validate()
