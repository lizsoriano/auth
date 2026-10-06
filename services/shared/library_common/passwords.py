"""Hash de contraseñas con bcrypt.

Es el MISMO algoritmo/formato que usa el monolito (Node `bcrypt`, `$2b$`), de modo que las cuentas creadas
en cualquier servicio sirven en el monolito y viceversa. bcrypt se importa al usarlo (los servicios que no
manejan contraseñas no lo necesitan instalado).
"""

BCRYPT_MAX_BYTES = 72  # límite del algoritmo; bcrypt ignora lo que exceda


def fits(password):
    return len(password.encode("utf-8")) <= BCRYPT_MAX_BYTES


def hash_password(password, rounds=12):
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(stored_hash, password):
    """True si coincide. Cualquier hash ilegible o de otro formato cuenta como False."""
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:BCRYPT_MAX_BYTES], stored_hash.encode("utf-8"))
    except (ValueError, TypeError, AttributeError):
        return False
