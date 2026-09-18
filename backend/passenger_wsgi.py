"""cPanel/Passenger entry point.

This host's Passenger calls application(environ, start_response) - plain
WSGI, no ASGI auto-detection - so the FastAPI (ASGI) app is wrapped with
a2wsgi's ASGIMiddleware rather than exposed directly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2wsgi import ASGIMiddleware

from main import app

application = ASGIMiddleware(app)
