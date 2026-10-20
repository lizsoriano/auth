import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gps_service import create_app  # noqa: E402


@pytest.fixture
def server():
    """Servidor real en un puerto libre: los WebSockets no se pueden probar con test_client."""
    app = create_app(history_size=5)
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{srv.server_port}"
    srv.shutdown()
    thread.join(timeout=5)
