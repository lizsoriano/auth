"""Lógica de autenticación: validación, hashing y ciclo de vida de la sesión.

No conoce Flask ni PostgreSQL: recibe un repositorio y un reloj, lo que permite
probarla sin base de datos.
"""
import hashlib
import ipaddress
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email

from . import passwords
from .errors import ApiError, EmailAlreadyExists
from .mailer import MailError

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,100}")

NAME_FIELDS = {
    "nombre": "nombre",
    "apellido_paterno": "apellido paterno",
    "apellido_materno": "apellido materno",
}
NAME_MAX = 120
DISPLAY_NAME_MAX = 150  # users.display_name es varchar(150) NOT NULL (lo exige el monolito)


def utcnow():
    return datetime.now(timezone.utc)


def public_user(row):
    """Datos del usuario aptos para exponer (nunca password_hash)."""
    return {
        "id": row["user_id"],
        "nombre": row["nombre"],
        "apellido_paterno": row["apellido_paterno"],
        "apellido_materno": row["apellido_materno"],
        "display_name": row["display_name"],
        "email": row["email"],
        "email_verified": row.get("email_verified_at") is not None,
        "created_at": row["created_at"],
    }


class AuthService:
    def __init__(self, repository, settings, clock=utcnow, mailer=None):
        self.repo = repository
        self.settings = settings
        self.clock = clock
        self.mailer = mailer
        # Hash ficticio para que un email inexistente cueste lo mismo que uno real.
        self._dummy_hash = passwords.hash_password(uuid.uuid4().hex, settings.bcrypt_rounds)

    # ---------------------------------------------------------------- registro
    def register(self, data):
        problems = []
        clean = {}
        for key, label in NAME_FIELDS.items():
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                problems.append({"field": key, "message": f"El campo {label} es obligatorio"})
            elif len(value.strip()) > NAME_MAX:
                problems.append({"field": key, "message": f"El campo {label} admite máximo {NAME_MAX} caracteres"})
            else:
                clean[key] = " ".join(value.split())

        email = self._validate_email(data.get("email"), problems)

        password = data.get("password")
        if not isinstance(password, str) or not password:
            problems.append({"field": "password", "message": "El campo password es obligatorio"})
        elif len(password) < self.settings.min_password_length:
            problems.append({"field": "password",
                             "message": f"La contraseña debe tener al menos {self.settings.min_password_length} caracteres"})
        elif not passwords.fits(password):
            problems.append({"field": "password",
                             "message": f"La contraseña admite máximo {passwords.BCRYPT_MAX_BYTES} bytes (límite de bcrypt)"})

        if problems:
            raise ApiError("validation_error", "Los datos enviados no son válidos", 400, problems)

        display_name = " ".join((clean["nombre"], clean["apellido_paterno"], clean["apellido_materno"]))[:DISPLAY_NAME_MAX]
        required = self.settings.email_confirmation_required
        token, verification = self._new_token(self.clock()) if required else (None, None)
        try:
            row = self.repo.create_user(
                clean["nombre"], clean["apellido_paterno"], clean["apellido_materno"], display_name,
                email, passwords.hash_password(password, self.settings.bcrypt_rounds),
                email_verified_at=None, verification=verification,
            )
        except EmailAlreadyExists:
            raise ApiError("email_exists", "El correo ya está registrado", 409)
        status = self._send_verification(row, token) if required else "not_required"
        return public_user(row), status

    # ------------------------------------------- confirmación del correo (Postfix)
    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _new_token(self, now):
        """Token aleatorio para el enlace; en la BD solo se guarda su SHA-256."""
        token = secrets.token_urlsafe(32)
        expires = now + timedelta(hours=self.settings.email_token_ttl_hours)
        return token, (self._hash_token(token), now, expires)

    def _send_verification(self, user_row, token):
        link = f"{self.settings.public_base_url}/verify/{token}"
        try:
            self.mailer.send_verification(user_row["email"], user_row["nombre"] or user_row["display_name"], link,
                                          self.settings.email_token_ttl_hours)
            return "sent"
        except MailError:
            return "failed"  # la cuenta existe; el usuario puede pedir otro enlace con /resend-verification

    def verify_email(self, token):
        """Devuelve (usuario, estado) con estado 'confirmed' | 'already_confirmed'."""
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
            raise ApiError("invalid_token", "El enlace de confirmación no es válido", 404)
        row = self.repo.get_verification(self._hash_token(token))
        if not row:
            raise ApiError("invalid_token", "El enlace de confirmación no es válido", 404)
        # Idempotente: los escáneres de enlaces (Gmail) pueden abrirlo antes que la persona.
        if row["used_at"] is not None or row["email_verified_at"] is not None:
            verified_at = row["email_verified_at"] or row["used_at"]
            return public_user({**row, "email_verified_at": verified_at}), "already_confirmed"
        now = self.clock()
        if row["expires_at"] <= now:
            raise ApiError("token_expired", "El enlace caducó. Solicita uno nuevo con POST /resend-verification", 410)
        self.repo.confirm_verification(row["verification_id"], row["user_id"], now)
        return public_user({**row, "email_verified_at": now}), "confirmed"

    def resend_verification(self, data):
        """Siempre responde igual exista o no el correo (no revela qué cuentas hay)."""
        email = data.get("email")
        if not isinstance(email, str) or not email.strip():
            raise ApiError("validation_error", "El campo email es obligatorio", 400)
        if not self.settings.email_confirmation_required:
            return
        user = self.repo.get_user_by_email(email.strip().lower())
        if not user or not user["is_active"] or user["email_verified_at"] is not None:
            return
        now = self.clock()
        last = self.repo.latest_verification_at(user["user_id"])
        if last is not None and (now - last).total_seconds() < self.settings.resend_cooldown_seconds:
            return  # enfriamiento: evita usar el servicio para inundar un buzón
        token, verification = self._new_token(now)
        self.repo.create_verification(user["user_id"], *verification)
        self._send_verification(user, token)

    def _validate_email(self, value, problems):
        if not isinstance(value, str) or not value.strip():
            problems.append({"field": "email", "message": "El campo email es obligatorio"})
            return None
        try:
            checked = validate_email(value.strip(), check_deliverability=self.settings.email_check_deliverability)
        except EmailNotValidError as exc:
            problems.append({"field": "email", "message": f"El email no es válido: {exc}"})
            return None
        return checked.normalized.lower()

    # ------------------------------------------------------------------- login
    def login(self, data, previous_session_id=None, ip_address=None, user_agent=None):
        email, password = data.get("email"), data.get("password")
        if not isinstance(email, str) or not email.strip() or not isinstance(password, str) or not password:
            raise ApiError("validation_error", "email y password son obligatorios", 400)
        user = self.repo.get_user_by_email(email.strip().lower())
        stored = user["password_hash"] if user else self._dummy_hash
        if not passwords.verify_password(stored, password) or not user:
            raise ApiError("invalid_credentials", "Correo o contraseña incorrectos", 401)
        if not user["is_active"]:
            raise ApiError("account_disabled", "La cuenta está desactivada", 403)
        if self.settings.email_confirmation_required and user["email_verified_at"] is None:
            raise ApiError("email_not_confirmed",
                           "Confirma tu correo antes de iniciar sesión: abre el enlace que enviamos a tu bandeja "
                           "o solicita otro con POST /resend-verification", 403)

        now = self.clock()
        if previous_session_id:
            self._revoke_quietly(previous_session_id, now)
        session_id = uuid.uuid4()
        expires_at = now + timedelta(minutes=self.settings.session_timeout_minutes)
        self.repo.start_session(user["user_id"], session_id, now, expires_at, self._clean_ip(ip_address),
                                (user_agent or "")[:400] or None)
        return public_user(user), session_id, expires_at

    @staticmethod
    def _clean_ip(value):
        try:
            return str(ipaddress.ip_address(value)) if value else None
        except ValueError:
            return None

    # ----------------------------------------------------------------- sesión
    def resolve_session(self, session_id):
        """Devuelve (estado, fila). estado: 'active' | 'expired' | 'missing'."""
        if not session_id:
            return "missing", None
        try:
            uuid.UUID(str(session_id))
        except ValueError:
            return "missing", None
        row = self.repo.get_session(session_id)
        if not row or row["revoked_at"] is not None or not row["is_active"]:
            return "missing", None
        if row["expires_at"] <= self.clock():
            return "expired", row
        return "active", row

    def session_info(self, row):
        remaining = int((row["expires_at"] - self.clock()).total_seconds())
        return {"expires_at": row["expires_at"], "expires_in_seconds": max(remaining, 0)}

    def logout(self, session_id):
        state, _ = self.resolve_session(session_id)
        if state == "active":
            self.repo.revoke_session(session_id, self.clock())
        return state

    def _revoke_quietly(self, session_id, when):
        try:
            uuid.UUID(str(session_id))
        except ValueError:
            return
        self.repo.revoke_session(session_id, when)
