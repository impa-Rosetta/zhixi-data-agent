from functools import lru_cache

from fastapi import HTTPException, status
from redis import Redis

from packages.platform_core.settings import get_settings


class LoginRateLimiter:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def check(self, key: str) -> None:
        settings = get_settings()
        redis_key = f"rate-limit:login:{key}"
        with self.client.pipeline() as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, settings.login_rate_window_seconds, nx=True)
            count, _ = pipe.execute()
        if int(count) > settings.login_rate_limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts")


@lru_cache
def get_login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter(Redis.from_url(get_settings().redis_url, decode_responses=True))
