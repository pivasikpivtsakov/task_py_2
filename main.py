"""
Дано:
    - в бд (JSONB) нужно хранить фильтры для запросов (не нормализованные)
    - запросов может быть несколько в одном фильтре на разные таблицы
    - нужно кешировать результат обработки фильтра (например 60 мин)

Задача:
    - выбрать и реализовать схему хранения этих запросов (учесть, что менять содержимое фильтров могут не разработчики

Доделать
    - добавить тип джоина в фильтр
    - избавиться от алхимии при генерации запроса
    - упростить редис, очень простая инвалидация при записи
"""


import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from sqlalchemy import URL, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.db import Base
from models.filter import compile_filter
from schema.filter import FilteredRequest


def _db_url() -> URL:
    return URL.create(
        drivername="postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
    )


engine = create_async_engine(_db_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _instance_to_dict(obj: Base) -> dict[str, Any]:
    return {attr.key: getattr(obj, attr.key) for attr in inspect(obj).mapper.column_attrs}


@app.post("/filtered")
async def filtered(
    payload: FilteredRequest,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, dict[str, Any]]]:
    stmt = compile_filter(primary_table=payload.table, tree=payload.filter)
    entities: list[type[Base]] = [desc["entity"] for desc in stmt.column_descriptions]

    result = await session.execute(stmt)
    return [
        {entity.__tablename__: _instance_to_dict(row[idx]) for idx, entity in enumerate(entities)}
        for row in result.all()
    ]
