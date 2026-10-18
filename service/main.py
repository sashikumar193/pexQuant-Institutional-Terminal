"""
AI-Trader Backend Server

项目结构：
- config.py   : 配置和环境变量
- database.py : 数据库初始化和连接
- utils.py    : 通用工具函数
- tasks.py    : 后台任务
- services.py : 业务逻辑服务
- routes.py   : API路由定义
- main.py     : 应用入口
"""

import secrets
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

# 1. Ensure current directory is in Python path for local imports on Vercel
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 2. Setup logging (Safe for Vercel Read-Only File System using /tmp)
handlers = [logging.StreamHandler(sys.stdout)]
try:
    LOG_DIR = os.path.join("/tmp", "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    handlers.append(
        RotatingFileHandler(
            os.path.join(LOG_DIR, "server.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
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

if os.getenv("API_STDERR_LOG", "false").strip().lower() in {"1", "true", "yes", "on"}:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))

logger = logging.getLogger(__name__)

# 3. Safe Import & Initialization with Diagnostic Fallback
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

    # Initialize database
    init_database()

    # Create app
    app = create_app()

    # ==================== Startup ====================

    @app.on_event("startup")
    async def startup_event():
        """Startup event - schedule background tasks."""
        try:
            db_status = get_database_status()
            logger.info(
                "Database ready: backend=%s details=%s",
                db_status.get("backend"),
                {key: value for key, value in db_status.items() if key != "backend"},
            )
            cache_status = get_cache_status()
            logger.info(
                "Cache ready: enabled=%s configured=%s available=%s prefix=%s client_installed=%s error=%s",
                cache_status.get("enabled"),
                cache_status.get("configured"),
                cache_status.get("available"),
                cache_status.get("prefix"),
                cache_status.get("client_installed"),
                cache_status.get("last_error"),
            )
            # Initialize trending cache
            logger.info("Initializing trending cache...")
            _update_trending_cache()
            if not background_tasks_enabled_for_api():
                logger.info(
                    "API background tasks disabled. Run `python service/server/worker.py` "
                    "to process prices, profit history, settlements, and market intel."
                )
                return

            started = start_background_tasks(logger)
            logger.info("Background tasks started: %s", len(started))
        except Exception as e:
            logger.error("Startup error: %s", e)

except Exception as e:
    # Fallback app: Agar koi module ya database fail ho, toh 500 error ke bajaye browser par exact error dikhaye
    from fastapi import FastAPI
    app = FastAPI()
    error_trace = traceback.format_exc()
    logger.error("Failed to initialize main app:\n%s", error_trace)

    @app.get("/{full_path:path}")
    def show_startup_error(full_path: str):
        return {
            "status": "startup_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": error_trace.splitlines()
        }


# ==================== Run ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
