import logging
import os

from gateway_service import create_app

logging.basicConfig(level=os.getenv("GATEWAY_LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
app = create_app()

if __name__ == "__main__":
    app.run(host=os.getenv("GATEWAY_HOST", "127.0.0.1"), port=int(os.getenv("GATEWAY_PORT", "8080")), threaded=True)
