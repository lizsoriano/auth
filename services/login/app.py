import sys

from login_service import ConfigError, Settings, create_app

try:
    settings = Settings.from_env()
    app = create_app(settings)
except ConfigError as exc:
    sys.exit(f"Error de configuración: {exc}")

if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
