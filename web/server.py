"""Web Dashboard 服务器

把 orchestrator.api 包装成带静态文件和 WebSocket 的版本。

启动方法：
    python -m uvicorn web.server:app --host 0.0.0.0 --port 8080

访问：
    http://localhost:8080/
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 复用 orchestrator 的 API
from orchestrator.api import app as orchestrator_app
from orchestrator.queue import make_queue
from orchestrator.metrics import render as render_metrics
from orchestrator.metrics_enhanced import alerts as metric_alerts

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Web Dashboard starting...")
    yield
    logger.info("Web Dashboard shutting down...")


# 用 orchestrator 的 app 加 WebSocket 和静态文件
app = orchestrator_app
app.router.lifespan_context = lifespan

# CORS（开发模式放开）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# === WebSocket：日志流 ===
class WebSocketLogHub:
    """管理多个 WebSocket 连接，转发日志"""
    def __init__(self):
        self.connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.connections.append(ws)
        await ws.send_json({"level": "success", "message": "已连接到日志流"})

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self.connections:
                self.connections.remove(ws)

    async def broadcast(self, message: Dict[str, Any]):
        async with self._lock:
            dead = []
            for ws in self.connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.connections.remove(ws)


log_hub = WebSocketLogHub()

@app.get("/alerts/recent")
async def alerts_recent(limit: int = 50):
    return {"alerts": metric_alerts.recent(limit=limit)}



@app.get("/")
async def index():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await log_hub.connect(ws)
    try:
        # 保持连接
        while True:
            data = await ws.receive_text()
            # Echo（前端可以发 ping）
            if data == "ping":
                await ws.send_json({"level": "info", "message": "pong"})
    except WebSocketDisconnect:
        await log_hub.disconnect(ws)


# === 把 orchestrator 内部日志也转发给前端 ===
class WebLogHandler(logging.Handler):
    """自定义 logging Handler，把日志广播给所有 WebSocket 连接"""
    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if level == "warning":
                level = "warn"
            asyncio.create_task(log_hub.broadcast({
                "level": level,
                "message": msg,
            }))
        except Exception:
            pass


# 挂到根 logger
root_logger = logging.getLogger()
ws_handler = WebLogHandler()
ws_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(name)s: %(message)s")
ws_handler.setFormatter(formatter)
root_logger.addHandler(ws_handler)


# === 额外的接口 ===

@app.get("/dashboard")
async def dashboard_page():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/api/v1/dashboard/summary")
async def dashboard_summary():
    """仪表盘聚合数据（一次拿全）"""
    queue = make_queue()
    return {
        "queue": queue.get_stats(),
        "recent": queue.get_recent_completed(limit=20),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
