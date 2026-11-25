"""
Production AI Agent — Part 6 Final Project.

Chạy: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "msg": record.getMessage(),
        }
        # Các field bổ sung truyền qua logger.info("...", extra={"fields": {...}})
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(settings.log_level)
logger.propagate = False


def log(event: str, **fields) -> None:
    logger.info(event, extra={"fields": {"event": event, **fields}})


# ── Graceful shutdown (tiêu chí 11) ──────────────────────────────────────────
# Khi nhận SIGTERM, uvicorn ngừng nhận kết nối mới, đợi request đang chạy xong
# rồi chạy phần shutdown của lifespan và thoát với exit code 0.
# Không tự đăng ký signal handler để không chặn cơ chế này của uvicorn.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port)
    yield
    log("shutdown", detail="SIGTERM received, in-flight requests completed")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log("request", method=request.method, path=request.url.path,
            status=status, ms=round((time.perf_counter() - start) * 1000, 1))


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Không lộ stack trace ra client, chỉ ghi vào log.
    logger.error("unhandled_error", exc_info=exc,
                 extra={"fields": {"event": "unhandled_error", "path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 503 khi Redis không kết nối được."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not ready")
    return {"status": "ready"}


def _estimate_tokens(text: str) -> int:
    # Ước lượng thô ~1.3 token / từ (mock LLM không trả usage thật).
    return max(1, int(len(text.split()) * 1.3))


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)   # 429 khi vượt giới hạn
    check_budget()              # 402 khi hết budget
    answer = llm_ask(body.question)
    cost = record_cost(_estimate_tokens(body.question), _estimate_tokens(answer))
    log("ask", user_id=body.user_id, question_len=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
