import time
from collections import defaultdict
from typing import ClassVar

from fastapi import HTTPException, Request, status

from app.core.security import get_client_ip


class RateLimiter:
    """Sliding-window in-memory rate limiter per IP address."""

    def __init__(self, requests_per_minute: int = 15, window_seconds: float = 60.0):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self.history: ClassVar[dict[str, list[float]]] = defaultdict(list)

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean timestamps older than window
        timestamps = [t for t in self.history[key] if t > cutoff]
        if len(timestamps) >= self.requests_per_minute:
            self.history[key] = timestamps
            return True

        timestamps.append(now)
        self.history[key] = timestamps
        return False

    def reset(self) -> None:
        """Clear history (useful for testing)."""
        self.history.clear()


auth_rate_limiter = RateLimiter(requests_per_minute=15, window_seconds=60.0)


async def check_auth_rate_limit(request: Request) -> None:
    ip = get_client_ip(request)
    if auth_rate_limiter.is_rate_limited(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please wait a minute and try again.",
        )
