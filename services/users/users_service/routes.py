"""Rutas de Users.

Permisos (JWT HS256 de 20 min, claims user_id y role_id):
  admin      -> todo.
  staff y customer -> solo su propia cuenta: GET /users/me, GET/PATCH /users/<su id>, PUT .../password (con su
                contraseña actual). No pueden listar usuarios, crear, borrar, ni cambiar rol o estado (403).
Sin token o con token inválido/revocado: 401. Rol insuficiente: 403.
"""
from email_validator import EmailNotValidError, validate_email
from library_common import ROLE_NAMES, ApiError, passwords
from library_common.serializers import render
from library_common.service_kit import claims, is_admin, json_body, page_args, role_payload

NAME_FIELDS = {"nombre": "nombre", "apellido_paterno": "apellido paterno", "apellido_materno": "apellido materno"}
NAME_MAX = 120
DISPLAY_NAME_MAX = 150
PATCH_FIELDS = ("email", "display_name", "nombre", "apellido_paterno", "apellido_materno", "role_id", "is_active")
ADMIN_ONLY_FIELDS = ("role_id", "is_active")


def _public(row):
    return {k: row[k] for k in ("user_id", "email", "display_name", "nombre", "apellido_paterno", "apellido_materno",
                                "role_id", "role_name", "is_active", "email_verified_at", "created_at")}


def _forbidden(message="No tienes permiso para esta operación."):
    return ApiError("forbidden", message, 403)


def _clean_name(data, key, label, problems, required=False):
    if key not in data or data[key] is None:
        if required:
            problems.append({"field": key, "message": f"El campo {label} es obligatorio"})
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        problems.append({"field": key, "message": f"El campo {label} no puede quedar vacío"})
    elif len(value.strip()) > NAME_MAX:
        problems.append({"field": key, "message": f"El campo {label} admite máximo {NAME_MAX} caracteres"})
    else:
        return " ".join(value.split())
    return None


def _clean_email(value, problems):
    if not isinstance(value, str) or not value.strip():
        problems.append({"field": "email", "message": "El campo email es obligatorio"})
        return None
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        problems.append({"field": "email", "message": f"El email no es válido: {exc}"})
        return None


def _check_password(value, settings, problems, field="password"):
    if not isinstance(value, str) or not value:
        problems.append({"field": field, "message": f"El campo {field} es obligatorio"})
    elif len(value) < settings.min_password_length:
        problems.append({"field": field,
                         "message": f"La contraseña debe tener al menos {settings.min_password_length} caracteres"})
    elif not passwords.fits(value):
        problems.append({"field": field,
                         "message": f"La contraseña admite máximo {passwords.BCRYPT_MAX_BYTES} bytes (límite de bcrypt)"})
    else:
        return value
    return None


def _role_id(value, problems):
    if isinstance(value, bool) or not isinstance(value, int) or value not in ROLE_NAMES:
        problems.append({"field": "role_id", "message": "role_id debe ser 1 (admin), 2 (staff) o 3 (customer)"})
        return None
    return value


def _validated(problems):
    if problems:
        raise ApiError("validation_error", "Los datos enviados no son válidos", 400, problems)


def register_routes(app, jwt_auth, repo, settings):
    any_user = jwt_auth.required()
    admin_only = jwt_auth.required(roles=("admin",))

    def must_exist(user_id):
        user = repo.get(user_id)
        if user is None:
            raise ApiError("not_found", f"No existe el usuario {user_id}", 404)
        return user

    def own_or_admin(user_id):
        c = claims()
        if not is_admin(c) and c["user_id"] != user_id:
            raise _forbidden("Solo puedes consultar o modificar tu propia cuenta.")
        return c

    @app.get("/roles")
    @any_user
    def roles():
        return render({"roles": role_payload()})

    @app.get("/users")
    @admin_only
    def list_users():
        limit, offset = page_args()
        users = [_public(u) for u in repo.list(limit, offset)]
        return render({"users": users, "limit": limit, "offset": offset})

    @app.get("/users/me")
    @any_user
    def me():
        return render({"user": _public(must_exist(claims()["user_id"]))})

    @app.get("/users/<int:user_id>")
    @any_user
    def get_user(user_id):
        own_or_admin(user_id)
        return render({"user": _public(must_exist(user_id))})

    @app.post("/users")
    @admin_only
    def create_user():
        data, problems = json_body(), []
        email = _clean_email(data.get("email"), problems)
        password = _check_password(data.get("password"), settings, problems)
        names = {k: _clean_name(data, k, label, problems, required=True) for k, label in NAME_FIELDS.items()}
        role_id = _role_id(data["role_id"], problems) if "role_id" in data else 3
        _validated(problems)
        display_name = (data.get("display_name") or " ".join(names.values()))[:DISPLAY_NAME_MAX].strip()
        user_id = repo.create(email, passwords.hash_password(password, settings.bcrypt_rounds), display_name,
                              names["nombre"], names["apellido_paterno"], names["apellido_materno"], role_id)
        return render({"message": "Usuario creado.", "user": _public(must_exist(user_id))}, 201)

    def apply_changes(user_id, data, *, replace):
        c = own_or_admin(user_id)
        problems, changes = [], {}
        unknown = [k for k in data if k not in PATCH_FIELDS]
        if unknown:
            problems.append({"field": ", ".join(unknown), "message": "Campo no permitido"})
        if not is_admin(c) and any(k in data for k in ADMIN_ONLY_FIELDS):
            raise _forbidden("Solo un administrador puede cambiar el rol o activar/desactivar cuentas.")
        if replace:
            missing = [k for k in PATCH_FIELDS if k not in data]
            if missing:
                problems.append({"field": ", ".join(missing), "message": "PUT exige todos los campos (usa PATCH para cambios parciales)"})
        if "email" in data:
            changes["email"] = _clean_email(data["email"], problems)
        for key, label in NAME_FIELDS.items():
            if key in data:
                changes[key] = _clean_name(data, key, label, problems)
        if "display_name" in data:
            value = data["display_name"]
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > DISPLAY_NAME_MAX:
                problems.append({"field": "display_name", "message": f"display_name es obligatorio (máximo {DISPLAY_NAME_MAX})"})
            else:
                changes["display_name"] = value.strip()
        if "role_id" in data:
            changes["role_id"] = _role_id(data["role_id"], problems)
        if "is_active" in data:
            if not isinstance(data["is_active"], bool):
                problems.append({"field": "is_active", "message": "is_active debe ser true o false"})
            else:
                changes["is_active"] = data["is_active"]
        if not changes and not problems:
            problems.append({"field": "", "message": "Envía al menos un campo para modificar"})
        _validated(problems)
        must_exist(user_id)
        repo.update(user_id, **changes)
        return render({"message": "Usuario actualizado.", "user": _public(must_exist(user_id))})

    @app.patch("/users/<int:user_id>")
    @any_user
    def patch_user(user_id):
        return apply_changes(user_id, json_body(), replace=False)

    @app.put("/users/<int:user_id>")
    @admin_only
    def put_user(user_id):
        return apply_changes(user_id, json_body(), replace=True)

    @app.put("/users/<int:user_id>/password")
    @any_user
    def set_password(user_id):
        c = own_or_admin(user_id)
        data, problems = json_body(), []
        new = _check_password(data.get("password"), settings, problems)
        _validated(problems)
        must_exist(user_id)
        if not is_admin(c):  # el dueño debe demostrar que conoce la contraseña actual
            current = data.get("current_password")
            stored = repo.password_hash(user_id)
            if not isinstance(current, str) or not stored or not passwords.verify_password(stored, current):
                raise ApiError("invalid_credentials", "La contraseña actual no es correcta", 401)
        repo.set_password(user_id, passwords.hash_password(new, settings.bcrypt_rounds))
        return render({"message": "Contraseña actualizada."})

    @app.delete("/users/<int:user_id>")
    @admin_only
    def delete_user(user_id):
        if claims()["user_id"] == user_id:
            raise ApiError("cannot_delete_self", "No puedes borrar tu propia cuenta.", 409)
        must_exist(user_id)
        repo.delete(user_id)
        return render({"message": "Usuario eliminado."})
