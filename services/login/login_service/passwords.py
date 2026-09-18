"""Hash de contraseñas con bcrypt.

Es el MISMO algoritmo/formato que usa el monolito (Node `bcrypt`, `$2b$`), de modo
que las cuentas creadas aquí sirven en el monolito y viceversa (p. ej. el
administrador creado con scripts/create-admin.js puede iniciar sesión).
"""
import bcrypt

BCRYPT_MAX_BYTES = 72  # límite del algoritmo; bcrypt ignora lo que exceda


def fits(password):
    return len(password.encode("utf-8")) <= BCRYPT_MAX_BYTES


def hash_password(password, rounds=12):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(stored_hash, password):
    """True si coincide. Cualquier hash ilegible o de otro formato cuenta como False."""
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:BCRYPT_MAX_BYTES], stored_hash.encode("utf-8"))
    except (ValueError, TypeError, AttributeError):
        return False
