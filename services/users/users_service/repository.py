"""Acceso a datos de Users: SOLO funciones SQL (fn_users_*, migración 008). users_service_user no tiene permiso
sobre ninguna tabla y no puede llamar funciones de otros servicios."""

USER_ERRORS = {
    "US001": (404, "not_found", None),      # el mensaje en español viene de la función SQL
    "US002": (409, "last_admin", None),
}


class UsersRepository:
    def __init__(self, pg):
        self.pg = pg

    def ping(self):
        self.pg.ping()

    def list(self, limit, offset):
        return self.pg.query("SELECT * FROM fn_users_list(%s, %s)", (limit, offset))

    def get(self, user_id):
        return self.pg.one("SELECT * FROM fn_users_get(%s)", (user_id,))

    def password_hash(self, user_id):
        row = self.pg.one("SELECT fn_users_get_password_hash(%s) AS h", (user_id,))
        return row["h"] if row else None

    def create(self, email, password_hash, display_name, nombre, apellido_paterno, apellido_materno, role_id):
        row = self.pg.one("SELECT fn_users_create(%s, %s, %s, %s, %s, %s, %s::smallint) AS id",
                          (email, password_hash, display_name, nombre, apellido_paterno, apellido_materno, role_id))
        return row["id"]

    def update(self, user_id, *, email=None, display_name=None, nombre=None, apellido_paterno=None,
               apellido_materno=None, role_id=None, is_active=None):
        """PATCH: None = conservar el valor actual."""
        self.pg.query("SELECT fn_users_update(%s, %s, %s, %s, %s, %s, %s::smallint, %s)",
                      (user_id, email, display_name, nombre, apellido_paterno, apellido_materno, role_id, is_active))

    def set_password(self, user_id, password_hash):
        self.pg.query("SELECT fn_users_set_password(%s, %s)", (user_id, password_hash))

    def delete(self, user_id):
        self.pg.query("SELECT fn_users_delete(%s)", (user_id,))
