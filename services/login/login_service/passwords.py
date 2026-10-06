"""Hash de contraseñas con bcrypt: vive en library_common para que todos los servicios usen el mismo."""
from library_common.passwords import BCRYPT_MAX_BYTES, fits, hash_password, verify_password  # noqa: F401
