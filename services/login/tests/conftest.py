import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from login_service import Settings, create_app  # noqa: E402
from login_service.errors import EmailAlreadyExists  # noqa: E402
from login_service.mailer import MailError  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class MemoryRepository:
    """Misma interfaz que PostgresRepository, en memoria."""

    def __init__(self):
        self.users, self.sessions, self.up, self.schema = {}, {}, True, True
        self.verifications = []  # dicts: verification_id, user_id, token_hash, created_at, expires_at, used_at

    def create_user(self, nombre, apellido_paterno, apellido_materno, display_name, email, password_hash,
                    email_verified_at=None, verification=None):
        if email in self.users:
            raise EmailAlreadyExists(email)
        row = dict(user_id=len(self.users) + 1, nombre=nombre, apellido_paterno=apellido_paterno,
                   apellido_materno=apellido_materno, display_name=display_name, email=email,
                   password_hash=password_hash, is_active=True, email_verified_at=email_verified_at,
                   created_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.users[email] = row
        if verification:
            self.create_verification(row["user_id"], *verification)
        return {k: v for k, v in row.items() if k != "password_hash"}

    def create_verification(self, user_id, token_hash, created_at, expires_at):
        self.verifications.append(dict(verification_id=len(self.verifications) + 1, user_id=user_id,
                                       token_hash=token_hash, created_at=created_at, expires_at=expires_at,
                                       used_at=None))

    def latest_verification_at(self, user_id):
        times = [v["created_at"] for v in self.verifications if v["user_id"] == user_id]
        return max(times) if times else None

    def get_verification(self, token_hash):
        v = next((v for v in self.verifications if v["token_hash"] == token_hash), None)
        if not v:
            return None
        u = next(u for u in self.users.values() if u["user_id"] == v["user_id"])
        return {**{k: val for k, val in u.items() if k != "password_hash"}, **v}

    def confirm_verification(self, verification_id, user_id, when):
        for v in self.verifications:
            if v["verification_id"] == verification_id and v["used_at"] is None:
                v["used_at"] = when
        for u in self.users.values():
            if u["user_id"] == user_id and u["email_verified_at"] is None:
                u["email_verified_at"] = when

    def get_user_by_email(self, email):
        return dict(self.users[email]) if email in self.users else None

    def start_session(self, user_id, session_id, created_at, expires_at, ip_address, user_agent):
        self.sessions[str(session_id)] = dict(session_id=session_id, user_id=user_id, expires_at=expires_at,
                                              revoked_at=None, ip=ip_address, ua=user_agent)

    def get_session(self, session_id):
        s = self.sessions.get(str(session_id))
        if not s:
            return None
        u = next(u for u in self.users.values() if u["user_id"] == s["user_id"])
        return {**{k: v for k, v in u.items() if k != "password_hash"}, **s}

    def revoke_session(self, session_id, when):
        s = self.sessions.get(str(session_id))
        if s and s["revoked_at"] is None:
            s["revoked_at"] = when

    def ping(self):
        if not self.up:
            raise RuntimeError("db down")
        return {"database": True, "schema": self.schema}


class FakeMailer:
    """Sustituye al SmtpMailer/Postfix: guarda lo que se habría enviado."""

    def __init__(self):
        self.sent, self.fail = [], False

    def send_verification(self, to_email, nombre, link, ttl_hours):
        if self.fail:
            raise MailError("postfix caído")
        self.sent.append(dict(to=to_email, nombre=nombre, link=link, ttl_hours=ttl_hours))

    @property
    def last_token(self):
        return self.sent[-1]["link"].rsplit("/", 1)[1].split("?")[0]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def repo():
    return MemoryRepository()


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def app(repo, clock, mailer):
    """Sesión/registro sin confirmación de correo (la confirmación se prueba en test_email_confirmation.py)."""
    settings = Settings(secret_key="test-secret-key-0123456789", session_timeout_minutes=30, bcrypt_rounds=4,
                        email_confirmation_required=False)
    return create_app(settings, repository=repo, clock=clock, mailer=mailer)


@pytest.fixture
def cm_settings():
    return Settings(secret_key="test-secret-key-0123456789", session_timeout_minutes=30, bcrypt_rounds=4,
                    email_confirmation_required=True, mail_from="Library <no-reply@example.com>",
                    public_base_url="http://vm.example:5000", email_token_ttl_hours=24, resend_cooldown_seconds=60)


@pytest.fixture
def cm_client(cm_settings, repo, clock, mailer):
    """Cliente con la confirmación por correo (Postfix) ACTIVADA, como en producción."""
    return create_app(cm_settings, repository=repo, clock=clock, mailer=mailer).test_client()


@pytest.fixture
def client(app):
    return app.test_client()


GOOD = {"nombre": "Ana", "apellido_paterno": "López", "apellido_materno": "Díaz",
        "email": "ana@example.com", "password": "ClaveSegura123"}


@pytest.fixture
def good():
    return dict(GOOD)
