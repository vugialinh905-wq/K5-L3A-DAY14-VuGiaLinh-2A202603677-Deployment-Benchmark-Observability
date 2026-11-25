"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

redis.from_url chỉ tạo client (lazy), không mở kết nối lúc import,
nên app vẫn khởi động được khi Redis chưa sẵn sàng.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: Redis không kết nối được → False."""
    try:
        return bool(r.ping())
    except Exception:
        return False
