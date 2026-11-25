"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

State nằm trong Redis nên mọi worker / instance dùng chung và vẫn còn sau
khi restart agent.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Vượt RATE_LIMIT_PER_MINUTE trong 60 giây → HTTP 429 kèm Retry-After."""
    # Không lưu API key thô vào tên key Redis.
    bucket = "rl:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)  # bỏ request ngoài cửa sổ
        pipe.zcard(bucket)                                       # đếm request còn lại
        _, count = pipe.execute()

        if count >= settings.rate_limit_per_minute:
            # Retry-After = thời gian tới khi request cũ nhất rời khỏi cửa sổ
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute",
                headers={"Retry-After": str(retry_after)},
            )

        pipe = r.pipeline()
        pipe.zadd(bucket, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        pipe.expire(bucket, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except Exception:
        # Redis chết: fail closed, không để request đi qua mà không giới hạn.
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
