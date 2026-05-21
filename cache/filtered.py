import hashlib
from typing import Any

from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError

from schema.filter import FilteredRequest

_KEY_PREFIX = "filter"
_KEY_ALGO = "sha256"

FilteredRows = list[dict[str, dict[str, Any] | None]]
_RESPONSE_ADAPTER: TypeAdapter[FilteredRows] = TypeAdapter(FilteredRows)


def make_filtered_cache_key(payload: FilteredRequest) -> str:
    digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    return f"{_KEY_PREFIX}:{_KEY_ALGO}:{digest}"


async def get_cached_filtered(
    *,
    client: Redis,
    key: str,
) -> FilteredRows | None:
    try:
        raw = await client.get(key)
    except RedisError:
        return None
    if raw is None:
        return None
    return _RESPONSE_ADAPTER.validate_json(raw)


async def set_cached_filtered(
    *,
    client: Redis,
    key: str,
    value: FilteredRows,
    ttl_s: int,
) -> None:
    payload = _RESPONSE_ADAPTER.dump_json(value)
    try:
        await client.set(key, payload, ex=ttl_s)
    except RedisError:
        return
