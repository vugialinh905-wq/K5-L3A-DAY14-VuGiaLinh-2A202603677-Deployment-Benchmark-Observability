"""
Cost guard (tiêu chí 8).

Cộng dồn chi phí LLM (theo token) vào Redis theo từng ngày (UTC).
Tổng chi phí >= DAILY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spent = float(r.get(_key()) or 0)
    except Exception:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Daily budget exhausted (${spent:.6f} / ${settings.daily_budget_usd})",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    try:
        key = _key()
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)          # INCRBYFLOAT là atomic, an toàn khi nhiều worker
        pipe.expire(key, 2 * 24 * 3600)      # giữ 2 ngày rồi tự xoá
        pipe.execute()
    except Exception:
        pass  # không làm hỏng response vì lỗi ghi sổ chi phí
    return cost
