"""Acceso a PostgreSQL con Psycopg 3.

Es el único módulo que importa psycopg. Solo toca `users` (tabla existente del
esquema `library`, ver data/) y `login_sessions` (nueva). No lee ni escribe el
catálogo de libros.
"""
import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from .errors import EmailAlreadyExists

USER_COLUMNS = ("user_id, nombre, apellido_paterno, apellido_materno, display_name, email, is_active, "
                "created_at, email_verified_at")


class PostgresRepository:
    def __init__(self, database_url, connect_timeout=5):
        self._url = database_url
        self._timeout = connect_timeout

    def _connect(self):
        # `with conn:` confirma al salir bien, revierte si hay excepción y cierra.
        return psycopg.connect(self._url, connect_timeout=self._timeout, row_factory=dict_row)

    def create_user(self, nombre, apellido_paterno, apellido_materno, display_name, email, password_hash,
                    email_verified_at=None, verification=None):
        """Crea la cuenta (y, si viene `verification`, su token) en UNA transacción.

        `verification` = (token_hash, created_at, expires_at). is_admin no se inserta
        (y el rol ni siquiera tiene permiso): siempre false.
        """
        query = f"""
            INSERT INTO users (nombre, apellido_paterno, apellido_materno, display_name, email, password_hash,
                               email_verified_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {USER_COLUMNS}
        """
        try:
            with self._connect() as conn:
                row = conn.execute(query, (nombre, apellido_paterno, apellido_materno, display_name, email,
                                           password_hash, email_verified_at)).fetchone()
                if verification:
                    self._insert_verification(conn, row["user_id"], *verification)
                return row
        except UniqueViolation:
            raise EmailAlreadyExists(email)

    @staticmethod
    def _insert_verification(conn, user_id, token_hash, created_at, expires_at):
        conn.execute(
            "INSERT INTO email_verifications (user_id, token_hash, created_at, expires_at) VALUES (%s, %s, %s, %s)",
            (user_id, token_hash, created_at, expires_at),
        )

    def create_verification(self, user_id, token_hash, created_at, expires_at):
        with self._connect() as conn:
            self._insert_verification(conn, user_id, token_hash, created_at, expires_at)

    def latest_verification_at(self, user_id):
        with self._connect() as conn:
            row = conn.execute("SELECT max(created_at) AS last FROM email_verifications WHERE user_id = %s",
                               (user_id,)).fetchone()
        return row["last"]

    def get_verification(self, token_hash):
        query = f"""
            SELECT v.verification_id, v.expires_at, v.used_at,
                   {", ".join("u." + c.strip() for c in USER_COLUMNS.split(","))}
              FROM email_verifications v
              JOIN users u ON u.user_id = v.user_id
             WHERE v.token_hash = %s
        """
        with self._connect() as conn:
            return conn.execute(query, (token_hash,)).fetchone()

    def confirm_verification(self, verification_id, user_id, when):
        """Marca el token como usado y la cuenta como verificada (misma transacción)."""
        with self._connect() as conn:
            conn.execute("UPDATE email_verifications SET used_at = %s WHERE verification_id = %s AND used_at IS NULL",
                         (when, verification_id))
            conn.execute("UPDATE users SET email_verified_at = %s WHERE user_id = %s AND email_verified_at IS NULL",
                         (when, user_id))

    def get_user_by_email(self, email):
        # Igual que el monolito: comparación insensible a mayúsculas.
        query = f"SELECT {USER_COLUMNS}, password_hash FROM users WHERE lower(email) = %s"
        with self._connect() as conn:
            return conn.execute(query, (email,)).fetchone()

    def start_session(self, user_id, session_id, created_at, expires_at, ip_address, user_agent):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO login_sessions (session_id, user_id, created_at, expires_at, ip_address, user_agent)
                   VALUES (%s, %s, %s, %s, %s::inet, %s)""",
                (session_id, user_id, created_at, expires_at, ip_address, user_agent),
            )

    def get_session(self, session_id):
        query = """
            SELECT s.session_id, s.created_at AS session_created_at, s.expires_at, s.revoked_at,
                   u.user_id, u.nombre, u.apellido_paterno, u.apellido_materno, u.display_name,
                   u.email, u.is_active, u.created_at, u.email_verified_at
              FROM login_sessions s
              JOIN users u ON u.user_id = s.user_id
             WHERE s.session_id = %s
        """
        with self._connect() as conn:
            return conn.execute(query, (session_id,)).fetchone()

    def revoke_session(self, session_id, when):
        with self._connect() as conn:
            conn.execute(
                "UPDATE login_sessions SET revoked_at = %s WHERE session_id = %s AND revoked_at IS NULL",
                (when, session_id),
            )

    def ping(self):
        """Devuelve {'database': bool, 'schema': bool}; lanza si no hay conexión."""
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
            row = conn.execute(
                """SELECT to_regclass('public.login_sessions') IS NOT NULL
                          AND to_regclass('public.email_verifications') IS NOT NULL
                          AND EXISTS (SELECT 1 FROM information_schema.columns
                                       WHERE table_schema = 'public' AND table_name = 'users'
                                         AND column_name = 'email_verified_at') AS schema_ok"""
            ).fetchone()
        return {"database": True, "schema": bool(row["schema_ok"])}
