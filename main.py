"""
Дано:
    - в бд (JSONB) нужно хранить фильтры для запросов (не нормализованные)
    - запросов может быть несколько в одном фильтре на разные таблицы
    - нужно кешировать результат обработки фильтра (например 60 мин)

Задача:
    - выбрать и реализовать схему хранения этих запросов
      (учесть, что менять содержимое фильтров могут не разработчики

Доделать
    - добавить тип джоина в фильтр
    - избавиться от алхимии при генерации запроса
    - упростить редис, очень простая инвалидация при записи

идея:
    - один фильтр на одну таблицу, то что щас это хардкор
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import Depends, FastAPI
from redis.asyncio import Redis

from cache.filtered import (
    get_cached_filtered,
    make_filtered_cache_key,
    set_cached_filtered,
)
from models.filter import compile_filter, decode_record
from schema.filter import FilteredRequest


class _PoolState:
    pool: asyncpg.Pool | None = None
    lock: asyncio.Lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    if _PoolState.pool is None:
        async with _PoolState.lock:
            if _PoolState.pool is None:
                _PoolState.pool = await asyncpg.create_pool(
                    user=os.environ["POSTGRES_USER"],
                    password=os.environ["POSTGRES_PASSWORD"],
                    host=os.environ["POSTGRES_HOST"],
                    port=int(os.environ["POSTGRES_PORT"]),
                    database=os.environ["POSTGRES_DB"],
                )
    assert _PoolState.pool is not None
    return _PoolState.pool


async def close_pool() -> None:
    if _PoolState.pool is not None:
        await _PoolState.pool.close()
        _PoolState.pool = None


redis_client: Redis = Redis(
    host=os.environ["REDIS_HOST"],
    port=int(os.environ["REDIS_PORT"]),
    db=int(os.environ["REDIS_DB"]),
)
CACHE_TTL_S: int = int(os.environ["CACHE_TTL_S"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await close_pool()
        await redis_client.aclose()


app = FastAPI(lifespan=lifespan)


async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


def get_redis() -> Redis:
    return redis_client


@app.post("/filtered")
async def filtered(
    payload: FilteredRequest,
    conn: asyncpg.Connection = Depends(get_connection),
    redis: Redis = Depends(get_redis),
) -> list[dict[str, dict[str, Any] | None]]:
    cache_key = make_filtered_cache_key(payload)
    cached = await get_cached_filtered(client=redis, key=cache_key)
    if cached is not None:
        return cached

    compiled = compile_filter(
        primary_table=payload.table,
        tree=payload.filter,
        joins=payload.joins,
    )
    records = await conn.fetch(compiled.sql, *compiled.params)
    rows = [decode_record(r) for r in records]

    await set_cached_filtered(
        client=redis,
        key=cache_key,
        value=rows,
        ttl_s=CACHE_TTL_S,
    )
    return rows
