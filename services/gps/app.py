import logging
import os

from gps_service import create_app

logging.basicConfig(level=os.getenv("GPS_LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
app = create_app()

if __name__ == "__main__":
    app.run(host=os.getenv("GPS_HOST", "0.0.0.0"), port=int(os.getenv("GPS_PORT", "5900")), threaded=True)
