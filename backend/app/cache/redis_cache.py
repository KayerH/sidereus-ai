from __future__ import annotations

import json
from typing import Any

import redis

from app.config import get_settings


class CacheManager:
    def __init__(self) -> None:
        settings = get_settings()
        self.ttl = settings.cache_ttl_seconds
        self._memory_cache: dict[str, Any] = {}
        self._client: redis.Redis | None = None

        if settings.redis_url:
            try:
                self._client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                self._client.ping()
            except redis.RedisError:
                self._client = None

    @property
    def backend_name(self) -> str:
        return "redis" if self._client else "memory-fallback"

    def get_json(self, key: str) -> Any | None:
        if self._client:
            try:
                value = self._client.get(key)
                return json.loads(value) if value else None
            except (redis.RedisError, json.JSONDecodeError):
                return None
        return self._memory_cache.get(key)

    def set_json(self, key: str, value: Any) -> None:
        if self._client:
            try:
                self._client.setex(key, self.ttl, json.dumps(value, ensure_ascii=False))
                return
            except (redis.RedisError, TypeError):
                pass
        self._memory_cache[key] = value
