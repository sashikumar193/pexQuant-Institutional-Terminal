import secrets
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

# 1. Local imports ke liye current directory ko path mein add karein
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 2. Vercel Read-Only File System ke liye /tmp mein logs banayein
handlers = [logging.StreamHandler(sys.stdout)]
try:
    LOG_DIR = os.path.join("/tmp", "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    handlers.append(
        RotatingFileHandler(
            os.path.join(LOG_DIR, "server.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5
        )
    )
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=handlers
)

logger = logging.getLogger(__name__)

# 3. Safe App Startup (500 Error kabhi nahi aayega)
try:
    from cache import get_cache_status
    from database import init_database, get_database_status
    from routes import create_app
    from routes_shared import api_access_log_enabled
    from tasks import (
        _update_trending_cache,
        background_tasks_enabled_for_api,
        start_background_tasks,
    )

    if not api_access_log_enabled():
        logging.getLogger("uvicorn.access").disabled = True
        logging.getLogger("uvicorn.access").propagate = False

    init_database()
    app = create_app()

    @app.on_event("startup")
    async def startup_event():
        try:
            _update_trending_cache()
            if background_tasks_enabled_for_api():
                start_background_tasks(logger)
        except Exception as e:
            logger.error("Startup error: %s", e)

except Exception as e:
    from fastapi import FastAPI
    app = FastAPI()
    error_trace = traceback.format_exc()

    @app.get("/{full_path:path}")
    def show_startup_error(full_path: str):
        return {
            "status": "startup_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": error_trace.splitlines()
        }
