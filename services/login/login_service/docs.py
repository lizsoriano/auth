"""Documentación OpenAPI 3 + Swagger UI (/docs) para los endpoints en XML y JSON.

Los ejemplos XML se generan con el mismo serializador que usa la API, así la
documentación no puede desincronizarse de las respuestas reales.
"""
import json

from flask import Blueprint, jsonify
from flask_swagger_ui import get_swaggerui_blueprint

from .serializers import error_payload
from .serializers import to_xml

docs_blueprint = Blueprint("docs", __name__)
swagger_ui_blueprint = get_swaggerui_blueprint(
    "/docs",
    "/openapi.json",
    config={"app_name": "Login service - Library", "defaultModelsExpandDepth": 1, "docExpansion": "list"},
)

_USER = {
    "id": 1, "nombre": "Ana", "apellido_paterno": "López", "apellido_materno": "Díaz",
    "display_name": "Ana López Díaz", "email": "ana@gmail.com", "email_verified": False,
    "role_id": 3, "role": "customer", "created_at": "2026-09-18T20:15:00+00:00",
}
_USER_OK = dict(_USER, email_verified=True)
_SESSION = {"expires_at": "2026-09-18T20:45:00+00:00", "expires_in_seconds": 1800}
_TOKENS = {"token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "Bearer", "token_expires_in_seconds": 1200,
           "refresh_token": "Xk3v_9mQ2-r7LwA0pYcN8sTzBhU4eDfGjKiOaMnPqRs"}


def _content(schema_ref, example):
    """Mismo recurso, dos representaciones: JSON (objeto) y XML (cadena)."""
    return {
        "application/xml": {"schema": {"$ref": schema_ref}, "example": '<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(example)},
        "application/json": {"schema": {"$ref": schema_ref}, "example": json.loads(json.dumps(example))},
    }


def _error(description, code, message, details=None):
    return {"description": description,
            "content": _content("#/components/schemas/ErrorResponse", error_payload(code, message, details))}


_FORMAT = {"$ref": "#/components/parameters/format"}


def build_spec():
    unauthenticated = _error("Sin sesión autenticada, o la sesión de 30 minutos caducó (`code` = `not_authenticated` o `session_expired`)",
                             "session_expired", "La sesión caducó (30 minutos). Inicia sesión de nuevo")
    bad_format = _error("Valor de `format` inválido", "invalid_format", "El parámetro format debe ser 'xml' o 'json'")
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Login service - Library",
            "version": "1.0.0",
            "description": (
                "Microservicio independiente de registro, autenticación y sesión.\n\n"
                "**Formato de respuesta:** todos los endpoints aceptan `?format=xml` o `?format=json`. "
                "Sin el parámetro la respuesta es **XML**.\n\n"
                "**Sesión:** `POST /login` crea una sesión de Flask (cookie `login_session`, HttpOnly) que dura "
                "**30 minutos**. Pasado ese tiempo `GET /session` responde `401` con `code = session_expired`.\n\n"
                "**Confirmación del correo:** `POST /register` envía un enlace por correo (Postfix de la instancia). "
                "Al abrirlo, `GET /verify/{token}` activa la cuenta y `POST /login` deja de responder `403 email_not_confirmed`. "
                "El enlace se abre en el navegador y muestra esta misma respuesta XML (no hay interfaz gráfica).\n\n"
                "Las peticiones (`POST`) se envían como JSON; las respuestas siguen el parámetro `format`."
            ),
        },
        "servers": [{"url": "/"}],
        "tags": [{"name": "Usuarios", "description": "Registro y cuenta"},
                 {"name": "Sesión", "description": "Login, consulta y cierre de sesión"},
                 {"name": "Operación", "description": "Estado del servicio"}],
        "paths": {
            "/register": {"post": {
                "tags": ["Usuarios"], "summary": "Registrar un nuevo usuario",
                "description": "Valida el formato del email y su unicidad. La contraseña se guarda solo como hash bcrypt en `users.password_hash`. "
                               "Envía el correo de confirmación por Postfix; `verification_email` indica `sent`, `failed` (usa /resend-verification) o `not_required`.",
                "parameters": [_FORMAT],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/RegisterRequest"},
                    "example": {"nombre": "Ana", "apellido_paterno": "López", "apellido_materno": "Díaz",
                                "email": "ana@example.com", "password": "ClaveSegura123"}}}},
                "responses": {
                    "201": {"description": "Usuario creado",
                            "content": _content("#/components/schemas/UserResponse", {"message": "Usuario registrado. Te enviamos un correo con un enlace de confirmación: ábrelo para activar la cuenta y después inicia sesión con POST /login.", "verification_email": "sent", "user": _USER})},
                    "400": _error("Datos inválidos o `format` inválido", "validation_error", "Los datos enviados no son válidos",
                                  [{"field": "email", "message": "El email no es válido: ..."}]),
                    "409": _error("El correo ya está registrado", "email_exists", "El correo ya está registrado"),
                },
            }},
            "/verify/{token}": {"get": {
                "tags": ["Usuarios"], "summary": "Confirmar el correo (enlace del mensaje)",
                "description": "Es el enlace que llega por correo. Idempotente: si ya estaba confirmada responde `status = already_confirmed`. "
                               "Vigencia del token: 24 h (`token_expired` -> 410).",
                "parameters": [{"name": "token", "in": "path", "required": True, "schema": {"type": "string"},
                                "description": "Token del enlace del correo"}, _FORMAT],
                "responses": {
                    "200": {"description": "Cuenta confirmada",
                            "content": _content("#/components/schemas/VerifyResponse",
                                                {"message": "Cuenta confirmada correctamente. Ya puedes iniciar sesión con POST /login.",
                                                 "status": "confirmed", "user": _USER_OK})},
                    "404": _error("Token inexistente o mal formado", "invalid_token", "El enlace de confirmación no es válido"),
                    "410": _error("Token caducado", "token_expired", "El enlace caducó. Solicita uno nuevo con POST /resend-verification"),
                },
            }},
            "/resend-verification": {"post": {
                "tags": ["Usuarios"], "summary": "Reenviar el correo de confirmación",
                "description": "Responde siempre 202 igual exista o no el correo (no revela cuentas). Máximo un envío por minuto por cuenta.",
                "parameters": [_FORMAT],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginRequest"}, "example": {"email": "ana@gmail.com"}}}},
                "responses": {
                    "202": {"description": "Solicitud aceptada",
                            "content": _content("#/components/schemas/MessageResponse",
                                                {"message": "Si el correo está registrado y pendiente de confirmar, enviaremos un nuevo enlace (máximo uno por minuto)."})},
                    "400": _error("Falta el email", "validation_error", "El campo email es obligatorio"),
                },
            }},
            "/login": {"post": {
                "tags": ["Sesión"], "summary": "Autenticar e iniciar sesión (JWT de 20 min + refresh token)",
                "description": "Verifica las credenciales contra PostgreSQL y crea la sesión (en Redis, 30 min sin actividad). Devuelve un **JWT HS256 de 20 minutos** (`token`, claims `user_id`, `role_id`, `jti`) para `Authorization: Bearer <token>` en todos los servicios, y un **refresh token de un solo uso** para renovarlo con `POST /token/refresh` antes de que caduque. La cookie `login_session` se devuelve en `Set-Cookie`.",
                "parameters": [_FORMAT],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginRequest"},
                    "example": {"email": "ana@example.com", "password": "ClaveSegura123"}}}},
                "responses": {
                    "200": {"description": "Sesión iniciada",
                            "headers": {"Set-Cookie": {"description": "Cookie de sesión `login_session` (HttpOnly)", "schema": {"type": "string"}}},
                            "content": _content("#/components/schemas/LoginResponse", {"message": "Sesión iniciada", "user": _USER_OK, "session": _SESSION, **_TOKENS})},
                    "400": _error("Faltan campos o `format` inválido", "validation_error", "email y password son obligatorios"),
                    "401": _error("Credenciales incorrectas", "invalid_credentials", "Correo o contraseña incorrectos"),
                    "403": _error("Correo sin confirmar (`email_not_confirmed`) o cuenta desactivada (`account_disabled`)",
                                  "email_not_confirmed", "Confirma tu correo antes de iniciar sesión: abre el enlace que enviamos a tu bandeja o solicita otro con POST /resend-verification"),
                    "503": _error("Redis no disponible: sin Redis no hay sesiones (falla cerrado)", "redis_unavailable",
                                  "No se puede verificar la sesión en este momento. Intenta de nuevo en unos segundos."),
                },
            }},
            "/token/refresh": {"post": {
                "tags": ["Sesión"], "summary": "Renovar el JWT antes de que caduque",
                "description": "Cambia el refresh token por un **JWT nuevo de 20 minutos** y un **refresh token nuevo**. El refresh token es de un solo uso (rotación) y el JWT anterior se revoca de inmediato (`jwt:revoked:<jti>`). Si la sesión ya se cerró o caducó, responde `401 invalid_refresh_token`. Renueva cuando falten unos minutos para que expire el JWT (p. ej. a los 15-18 min).",
                "parameters": [_FORMAT],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/RefreshRequest"},
                    "example": {"refresh_token": _TOKENS["refresh_token"]}}}},
                "responses": {
                    "200": {"description": "Token renovado",
                            "content": _content("#/components/schemas/RefreshResponse",
                                                {"message": "Token renovado. El refresh token anterior ya no sirve: usa el nuevo.",
                                                 "session": _SESSION, **_TOKENS})},
                    "400": _error("Cuerpo inválido o `format` inválido", "invalid_body", "El cuerpo debe ser un objeto JSON válido codificado en UTF-8"),
                    "401": _error("Refresh token inválido, ya usado, o la sesión caducó/se cerró", "invalid_refresh_token",
                                  "El refresh token no es válido, ya se usó o la sesión caducó. Inicia sesión de nuevo con POST /login"),
                    "403": _error("La cuenta fue desactivada", "account_disabled", "La cuenta está desactivada"),
                    "503": _error("Redis no disponible (falla cerrado)", "redis_unavailable",
                                  "No se puede verificar la sesión en este momento. Intenta de nuevo en unos segundos."),
                },
            }},
            "/logout": {"post": {
                "tags": ["Sesión"], "summary": "Cerrar la sesión",
                "description": "Cierra la sesión de verdad: **revoca el JWT** (`jwt:revoked:<jti>`), **borra el refresh token y la sesión de Redis**, marca la fila de auditoría en PostgreSQL y borra la cookie. A partir de ese momento ningún servicio acepta ese JWT.",
                "security": [{"cookieAuth": []}], "parameters": [_FORMAT],
                "responses": {
                    "200": {"description": "Sesión cerrada",
                            "content": _content("#/components/schemas/MessageResponse", {"message": "Sesión cerrada"})},
                    "400": bad_format,
                    "401": unauthenticated,
                },
            }},
            "/session": {"get": {
                "tags": ["Sesión"], "summary": "Consultar la sesión actual",
                "description": "Devuelve el usuario autenticado y el tiempo restante. Tras 30 minutos responde `401` con `code = session_expired`.",
                "security": [{"cookieAuth": []}], "parameters": [_FORMAT],
                "responses": {
                    "200": {"description": "Sesión activa",
                            "content": _content("#/components/schemas/SessionResponse", {"authenticated": True, "user": _USER_OK, "session": _SESSION})},
                    "400": bad_format,
                    "401": unauthenticated,
                },
            }},
            "/health": {"get": {
                "tags": ["Operación"], "summary": "Estado del servicio, PostgreSQL y Redis",
                "parameters": [_FORMAT],
                "responses": {
                    "200": {"description": "Servicio y base de datos disponibles",
                            "content": _content("#/components/schemas/HealthResponse",
                                                {"status": "ok", "service": "login", "database": "connected", "schema": "ok", "redis": "ok"})},
                    "400": bad_format,
                    "503": _error("PostgreSQL o Redis no disponibles, o faltan las tablas del servicio", "database_unavailable",
                                  "El servicio está activo pero PostgreSQL no está disponible"),
                },
            }},
        },
        "components": {
            "securitySchemes": {"cookieAuth": {"type": "apiKey", "in": "cookie", "name": "login_session",
                                               "description": "Cookie de sesión emitida por POST /login"}},
            "parameters": {"format": {
                "name": "format", "in": "query", "required": False,
                "description": "Formato de la respuesta. Por defecto `xml`.",
                "schema": {"type": "string", "enum": ["xml", "json"], "default": "xml"}}},
            "schemas": {
                "RegisterRequest": {"type": "object", "required": ["nombre", "apellido_paterno", "apellido_materno", "email", "password"],
                                    "properties": {"nombre": {"type": "string", "maxLength": 120},
                                                   "apellido_paterno": {"type": "string", "maxLength": 120},
                                                   "apellido_materno": {"type": "string", "maxLength": 120},
                                                   "email": {"type": "string", "format": "email"},
                                                   "password": {"type": "string", "format": "password", "minLength": 8, "description": "8 caracteres mínimo; máximo 72 bytes (límite de bcrypt)"}}},
                "LoginRequest": {"type": "object", "required": ["email", "password"],
                                 "properties": {"email": {"type": "string", "format": "email"},
                                                "password": {"type": "string", "format": "password"}}},
                "User": {"type": "object", "xml": {"name": "user"},
                         "properties": {"id": {"type": "integer"}, "nombre": {"type": "string", "nullable": True, "description": "NULL en cuentas creadas por el monolito"},
                                        "apellido_paterno": {"type": "string", "nullable": True}, "apellido_materno": {"type": "string", "nullable": True},
                                        "email": {"type": "string", "format": "email"},
                                        "email_verified": {"type": "boolean", "description": "false hasta abrir el enlace del correo"},
                                        "role_id": {"type": "integer", "description": "1 admin, 2 staff, 3 customer (va en el JWT)"},
                                        "role": {"type": "string", "enum": ["admin", "staff", "customer"]},
                                        "display_name": {"type": "string", "description": "Nombre completo (columna users.display_name, compartida con el monolito)"},
                                        "created_at": {"type": "string", "format": "date-time"}}},
                "SessionInfo": {"type": "object", "xml": {"name": "session"},
                                "properties": {"expires_at": {"type": "string", "format": "date-time"},
                                               "expires_in_seconds": {"type": "integer"}}},
                "MessageResponse": {"type": "object", "xml": {"name": "response"}, "properties": {"message": {"type": "string"}}},
                "UserResponse": {"type": "object", "xml": {"name": "response"},
                                 "properties": {"message": {"type": "string"},
                                                "verification_email": {"type": "string", "enum": ["sent", "failed", "not_required"]},
                                                "user": {"$ref": "#/components/schemas/User"}}},
                "VerifyResponse": {"type": "object", "xml": {"name": "response"},
                                   "properties": {"message": {"type": "string"},
                                                  "status": {"type": "string", "enum": ["confirmed", "already_confirmed"]},
                                                  "user": {"$ref": "#/components/schemas/User"}}},
                "TokenFields": {"type": "object", "properties": {
                    "token": {"type": "string", "description": "JWT HS256 de 20 minutos: Authorization: Bearer <token>"},
                    "token_type": {"type": "string", "enum": ["Bearer"]},
                    "token_expires_in_seconds": {"type": "integer", "example": 1200},
                    "refresh_token": {"type": "string", "description": "De un solo uso; se cambia por otro con POST /token/refresh"}}},
                "RefreshRequest": {"type": "object", "required": ["refresh_token"],
                                   "properties": {"refresh_token": {"type": "string"}}},
                "LoginResponse": {"type": "object", "xml": {"name": "response"},
                                  "allOf": [{"$ref": "#/components/schemas/TokenFields"}],
                                  "properties": {"message": {"type": "string"}, "user": {"$ref": "#/components/schemas/User"},
                                                 "session": {"$ref": "#/components/schemas/SessionInfo"}}},
                "RefreshResponse": {"type": "object", "xml": {"name": "response"},
                                    "allOf": [{"$ref": "#/components/schemas/TokenFields"}],
                                    "properties": {"message": {"type": "string"},
                                                   "session": {"$ref": "#/components/schemas/SessionInfo"}}},
                "SessionResponse": {"type": "object", "xml": {"name": "response"},
                                    "properties": {"authenticated": {"type": "boolean"}, "user": {"$ref": "#/components/schemas/User"},
                                                   "session": {"$ref": "#/components/schemas/SessionInfo"}}},
                "HealthResponse": {"type": "object", "xml": {"name": "response"},
                                   "properties": {"status": {"type": "string"}, "service": {"type": "string"},
                                                  "database": {"type": "string"}, "schema": {"type": "string"},
                                                  "redis": {"type": "string"}}},
                "ErrorResponse": {"type": "object", "xml": {"name": "response"}, "properties": {"error": {
                    "type": "object", "properties": {
                        "code": {"type": "string", "description": "validation_error, invalid_body, invalid_format, email_exists, invalid_credentials, email_not_confirmed, account_disabled, invalid_token, token_expired, not_authenticated, session_expired, invalid_refresh_token, redis_unavailable, database_unavailable, schema_missing, internal_error"},
                        "message": {"type": "string"},
                        "details": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "message": {"type": "string"}}}}}}}},
            },
        },
    }


@docs_blueprint.get("/openapi.json")
def openapi():
    return jsonify(build_spec())
