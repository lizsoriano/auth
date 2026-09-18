from flask import Blueprint, current_app, request, session

from .auth import public_user
from .errors import ApiError
from .serializers import error_payload, render, requested_format

api = Blueprint("api", __name__)


def _service():
    return current_app.extensions["auth_service"]


def _body():
    """Cuerpo JSON (o formulario). Debe ser un objeto."""
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError("invalid_body", "El cuerpo debe ser un objeto JSON válido codificado en UTF-8", 400)
        return data
    if request.form:
        return request.form.to_dict()
    raise ApiError("invalid_body", "Envía el cuerpo como JSON (Content-Type: application/json) o formulario", 400)


def _session_expired():
    return ApiError("session_expired", "La sesión caducó (30 minutos). Inicia sesión de nuevo", 401)


def _not_authenticated():
    return ApiError("not_authenticated", "No hay una sesión autenticada", 401)


@api.before_request
def _validate_format():
    requested_format()  # lanza 400 si format no es xml/json


@api.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


REGISTER_MESSAGES = {
    "sent": "Usuario registrado. Te enviamos un correo con un enlace de confirmación: ábrelo para activar la cuenta "
            "y después inicia sesión con POST /login.",
    "failed": "Usuario registrado, pero no pudimos enviar el correo de confirmación. "
              "Solicita otro enlace con POST /resend-verification.",
    "not_required": "Usuario registrado correctamente. Ya puedes iniciar sesión con POST /login.",
}


@api.post("/register")
def register():
    user, status = _service().register(_body())
    return render({"message": REGISTER_MESSAGES[status], "verification_email": status, "user": user}, 201)


@api.get("/verify/<token>")
def verify(token):
    user, state = _service().verify_email(token)
    message = ("Cuenta confirmada correctamente. Ya puedes iniciar sesión con POST /login."
               if state == "confirmed" else
               "Esta cuenta ya estaba confirmada. Ya puedes iniciar sesión con POST /login.")
    return render({"message": message, "status": state, "user": user})


@api.post("/resend-verification")
def resend_verification():
    _service().resend_verification(_body())
    return render({"message": "Si el correo está registrado y pendiente de confirmar, enviaremos un nuevo enlace "
                              "(máximo uno por minuto)."}, 202)


@api.post("/login")
def login():
    service = _service()
    user, session_id, expires_at = service.login(
        _body(),
        previous_session_id=session.get("sid"),
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    session.clear()
    session.permanent = True
    session["sid"] = str(session_id)
    info = {"expires_at": expires_at, "expires_in_seconds": service.settings.session_timeout_minutes * 60}
    return render({"message": "Sesión iniciada", "user": user, "session": info})


@api.post("/logout")
def logout():
    service = _service()
    state = service.logout(session.get("sid"))
    session.clear()
    if state == "missing":
        raise _not_authenticated()
    if state == "expired":
        raise _session_expired()
    return render({"message": "Sesión cerrada"})


@api.get("/session")
def current_session():
    service = _service()
    state, row = service.resolve_session(session.get("sid"))
    if state == "missing":
        session.clear()
        raise _not_authenticated()
    if state == "expired":
        raise _session_expired()
    return render({"authenticated": True, "user": public_user(row), "session": service.session_info(row)})


@api.get("/health")
def health():
    try:
        status = current_app.extensions["repository"].ping()
    except Exception:
        current_app.logger.exception("health: PostgreSQL no disponible")
        raise ApiError("database_unavailable", "El servicio está activo pero PostgreSQL no está disponible", 503)
    if not status["schema"]:
        raise ApiError("schema_missing",
                       "PostgreSQL responde pero faltan las tablas del servicio (aplica data/001_login_schema.sql)", 503)
    return render({"status": "ok", "service": "login", "database": "connected", "schema": "ok"})


def register_error_handlers(app):
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return render(error_payload(exc.code, exc.message, exc.details), exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return render(error_payload(exc.name.lower().replace(" ", "_"), exc.description), exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("Error no controlado")
        return render(error_payload("internal_error", "Error interno del servidor"), 500)
