"""CLI para dar de alta (o rotar) un usuario de WS-Security en
soap_service_credenciales, sin tener que escribir SQL a mano.

Uso:
    python scripts/crear_credencial_reportes.py --usuario reportes
    python scripts/crear_credencial_reportes.py --usuario reportes --password "unaClaveSegura123"

Si se omite --password, se pide de forma interactiva (getpass, no queda
en el historial de la shell).

Cifra la contraseña con Fernet (paquete `cryptography`) usando la clave
maestra `WSSE_MASTER_KEY` del `.env` del servidor y guarda el resultado
en `password_cifrada`. La contraseña en claro NUNCA se escribe a disco;
solo existe en memoria durante esta ejecución. Ver soap/security.py para
la justificación completa de por qué se cifra (reversible) en vez de
hashear (irreversible): el perfil WS-Security PasswordDigest necesita
recuperar la contraseña real para validar, algo imposible con un hash.

IMPORTANTE: el cliente SOAP que vaya a invocar ObtenerEstadisticasPorModelo
sí necesita la contraseña EN CLARO original (la misma que se pasó a este
script) para construir su UsernameToken/PasswordDigest — es la que el
usuario del curso debe entregar/recordar, no ningún valor derivado.
"""
import argparse
import getpass
import sys
from pathlib import Path

from cryptography.fernet import Fernet

# Permite ejecutar este script directamente (python scripts/archivo.py)
# sin instalar el proyecto como paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Config  # noqa: E402
from db.connection import get_admin_connection  # noqa: E402


def cifrar_password(password: str, master_key: str) -> str:
    fernet = Fernet(master_key.encode("utf-8"))
    return fernet.encrypt(password.encode("utf-8")).decode("ascii")


def main():
    parser = argparse.ArgumentParser(
        description="Crea o rota una credencial WS-Security en soap_service_credenciales."
    )
    parser.add_argument("--usuario", required=True, help="Nombre de usuario (wsse:Username).")
    parser.add_argument(
        "--password",
        default=None,
        help="Contraseña en claro. Si se omite, se pide de forma interactiva.",
    )
    args = parser.parse_args()

    if not Config.WSSE_MASTER_KEY:
        print(
            "Error: WSSE_MASTER_KEY no está configurada en .env. Genere una con:\n"
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
            file=sys.stderr,
        )
        sys.exit(1)

    password = args.password if args.password is not None else getpass.getpass("Contraseña: ")
    if not password:
        print("Error: la contraseña no puede estar vacía.", file=sys.stderr)
        sys.exit(1)

    password_cifrada = cifrar_password(password, Config.WSSE_MASTER_KEY)

    try:
        with get_admin_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO soap_service_credenciales (usuario, password_cifrada)
                    VALUES (%s, %s)
                    ON CONFLICT (usuario) DO UPDATE
                        SET password_cifrada = EXCLUDED.password_cifrada
                    """,
                    (args.usuario, password_cifrada),
                )
            conn.commit()
    except Exception as exc:
        print(f"Error al guardar la credencial: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Credencial creada/actualizada para usuario '{args.usuario}'.")
    print()
    print(
        "El cliente SOAP debe usar la MISMA contraseña en claro que acaba de "
        "ingresar (no un valor derivado) para construir su UsernameToken/"
        "PasswordDigest al invocar ObtenerEstadisticasPorModelo."
    )


if __name__ == "__main__":
    main()
