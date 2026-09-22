"""WS-Security: UsernameToken con PasswordDigest (docs/CONTRATO_DISENO.md §5).

Protege únicamente ObtenerEstadisticasPorModelo. Desacoplado de
soap/service.py: el service solo llama a validar_header(header_el, conn)
y deja que este módulo lance faults.AutenticacionFallidaError si algo
falla.

--------------------------------------------------------------------
DECISIÓN DE DISEÑO (ver docs/ENGINEERING_DECISIONS.md ED-07):

PasswordDigest exige que el servidor pueda reconstruir
Base64(SHA1(nonce + created + password)), lo que por definición requiere
la contraseña real (o un equivalente reversible) del lado servidor. Un
hash unidireccional (SHA-256, bcrypt) es incompatible con ese perfil: si
se usara el hash mismo como "password" en la fórmula, ese hash pasaría a
ser el secreto de autenticación real — ni más ni menos seguro que
guardar la contraseña en claro, porque una fuga de esa sola fila ya
permite autenticarse sin conocer la contraseña original.

La solución correcta usada aquí: `soap_service_credenciales.password_cifrada`
guarda la contraseña CIFRADA (no hasheada) con Fernet (AES simétrico
autenticado, paquete `cryptography`), usando una clave maestra
(`WSSE_MASTER_KEY`) que vive SOLO en la variable de entorno del servidor
— nunca en la base de datos ni en el repositorio. Para validar un
digest, el servidor descifra con esa clave para recuperar la contraseña
real, y con ESA calcula el digest clásico. Una fuga de la base de datos
por sí sola no basta para autenticarse (falta la clave maestra):
defensa en profundidad, y el perfil PasswordDigest queda implementado
correctamente en vez de simplificado.
--------------------------------------------------------------------
"""
import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from config.settings import Config
from db import repository
from soap import envelope, faults

logger = logging.getLogger(__name__)

# Nonces vistos recientemente, para impedir replay dentro de la ventana
# de tolerancia: clave (usuario, nonce_base64) -> epoch de expiración.
# Un dict en memoria del proceso es suficiente para este ejercicio (un
# único proceso Flask de desarrollo); no sobrevive a un reinicio ni se
# comparte entre workers, lo cual está documentado como límite conocido.
_nonces_vistos = {}

MENSAJE_GENERICO = (
    "Autenticación fallida: credenciales inválidas o cabecera WS-Security ausente."
)


def _limpiar_nonces_expirados(ahora_epoch):
    expirados = [clave for clave, expira in _nonces_vistos.items() if expira <= ahora_epoch]
    for clave in expirados:
        del _nonces_vistos[clave]


def _parse_created(created_str):
    """Parsea un wsu:Created tipo '2026-09-03T12:00:00Z' a datetime aware."""
    valor = created_str.strip()
    if valor.endswith("Z"):
        valor = valor[:-1] + "+00:00"
    dt = datetime.fromisoformat(valor)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validar_header(header_el, conn):
    """Valida un wsse:UsernameToken/PasswordDigest.

    Lanza faults.AutenticacionFallidaError con el MISMO mensaje genérico
    ante cualquier problema (header ausente, usuario inexistente, digest
    incorrecto, ventana vencida, nonce repetido) — nunca se revela cuál
    de esas cosas falló, para no dar pistas a un atacante.
    """
    security_el = envelope.get_child(header_el, "Security", ns=envelope.WSSE_NS)
    if security_el is None:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    token_el = envelope.get_child(security_el, "UsernameToken", ns=envelope.WSSE_NS)
    if token_el is None:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    usuario = envelope.get_text(token_el, "Username", ns=envelope.WSSE_NS)
    password_el = envelope.get_child(token_el, "Password", ns=envelope.WSSE_NS)
    nonce_el = envelope.get_child(token_el, "Nonce", ns=envelope.WSSE_NS)
    created = envelope.get_text(token_el, "Created", ns=envelope.WSU_NS)

    if not usuario or password_el is None or nonce_el is None or not created:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    tipo_password = password_el.get("Type", "")
    if "PasswordDigest" not in tipo_password:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    digest_recibido = (password_el.text or "").strip()
    nonce_b64 = (nonce_el.text or "").strip()
    if not digest_recibido or not nonce_b64:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    try:
        creado_en = _parse_created(created)
    except ValueError:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    ahora = datetime.now(timezone.utc)
    ventana = Config.WSSE_NONCE_WINDOW_SECONDS
    if abs((ahora - creado_en).total_seconds()) > ventana:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    epoch_ahora = time.time()
    _limpiar_nonces_expirados(epoch_ahora)
    clave_nonce = (usuario, nonce_b64)
    if clave_nonce in _nonces_vistos:
        # Replay: mismo nonce ya usado dentro de la ventana de tolerancia.
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    credencial = repository.obtener_credencial(conn, usuario)
    if credencial is None:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    try:
        nonce_bytes = base64.b64decode(nonce_b64, validate=True)
    except Exception:
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    # Ver docstring del módulo: se descifra (no se compara un hash) para
    # recuperar la contraseña real y calcular el digest clásico con ella.
    if not Config.WSSE_MASTER_KEY:
        logger.error(
            "WSSE_MASTER_KEY no está configurada; no se puede validar WS-Security."
        )
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    try:
        fernet = Fernet(Config.WSSE_MASTER_KEY.encode("utf-8"))
        password_real = fernet.decrypt(credencial["password_cifrada"].encode("utf-8"))
    except (InvalidToken, ValueError):
        # Clave maestra incorrecta o dato corrupto: nunca se distingue de
        # "usuario no encontrado" ante el cliente (mismo mensaje genérico).
        logger.error("No se pudo descifrar password_cifrada para usuario '%s'.", usuario)
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    digest_esperado = base64.b64encode(
        hashlib.sha1(nonce_bytes + created.encode("utf-8") + password_real).digest()
    ).decode("ascii")

    if not hmac.compare_digest(digest_esperado, digest_recibido):
        raise faults.AutenticacionFallidaError(MENSAJE_GENERICO)

    # El nonce solo se marca "usado" tras una validación completa y
    # exitosa: si se marcara antes, un atacante podría "quemar" nonces
    # legítimos enviando digests incorrectos con nonces ajenos capturados.
    _nonces_vistos[clave_nonce] = epoch_ahora + ventana
    logger.info("WS-Security: autenticación exitosa para usuario '%s'.", usuario)
