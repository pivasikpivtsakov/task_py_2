import operator
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, inspect, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from models.db import Base, TABLE_REGISTRY
from schema.filter import (
    ComparisonNodeSchema,
    ComparisonOp,
    FilterNodeSchema,
    JoinType,
    LogicalNodeSchema,
    LogicalOp,
)

_OP_BUILDERS: dict[ComparisonOp, Callable[[Any, Any], ColumnElement[bool]]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "in": lambda col, val: col.in_(val),
    "nin": lambda col, val: col.notin_(val),
}

_LOGICAL_BUILDERS: dict[LogicalOp, Callable[..., ColumnElement[bool]]] = {
    "and": and_,
    "or": or_,
}


def _collect_tables(node: FilterNodeSchema) -> set[str]:
    if isinstance(node, LogicalNodeSchema):
        result: set[str] = set()
        for child in node.children:
            result.update(_collect_tables(child))
        return result
    return {node.table}


def _resolve_column(table: str, field: str) -> InstrumentedAttribute[Any]:
    if table not in TABLE_REGISTRY:
        raise ValueError(f"unknown table '{table}'")
    model = TABLE_REGISTRY[table]
    column_keys = {col.key for col in inspect(model).columns}
    if field not in column_keys:
        raise ValueError(f"unknown field '{table}.{field}'")
    return getattr(model, field)


def _resolve_join(primary: type[Base], target_table: str) -> InstrumentedAttribute[Any]:
    for rel in inspect(primary).relationships:
        if rel.entity.class_.__tablename__ == target_table:
            return getattr(primary, rel.key)
    raise ValueError(
        f"no relationship from '{primary.__tablename__}' to '{target_table}'; "
        f"declare one on the SQLAlchemy model to make it joinable"
    )


def _to_clause(node: FilterNodeSchema) -> ColumnElement[bool]:
    if isinstance(node, LogicalNodeSchema):
        return _LOGICAL_BUILDERS[node.op](*(_to_clause(child) for child in node.children))
    column = _resolve_column(table=node.table, field=node.field)
    return _OP_BUILDERS[node.op](column, node.value)


def compile_filter(
    *,
    primary_table: str,
    tree: FilterNodeSchema,
    joins: Mapping[str, JoinType] | None = None,
) -> Select[Any]:
    if primary_table not in TABLE_REGISTRY:
        raise ValueError(f"unknown primary table '{primary_table}'")
    primary = TABLE_REGISTRY[primary_table]
    joins = joins or {}

    referenced = _collect_tables(tree)
    referenced.discard(primary_table)
    unknown = sorted(t for t in referenced if t not in TABLE_REGISTRY)
    if unknown:
        raise ValueError(f"unknown referenced tables: {unknown}")

    if primary_table in joins:
        raise ValueError(f"cannot declare a join for the primary table '{primary_table}'")
    unknown_join_targets = sorted(t for t in joins if t not in TABLE_REGISTRY)
    if unknown_join_targets:
        raise ValueError(f"unknown join target tables: {unknown_join_targets}")

    related = sorted(referenced | joins.keys())
    related_models = [TABLE_REGISTRY[t] for t in related]
    stmt = select(primary, *related_models)
    for related_table in related:
        relationship = _resolve_join(primary=primary, target_table=related_table)
        if joins.get(related_table, "inner") == "left":
            stmt = stmt.outerjoin(relationship)
        else:
            stmt = stmt.join(relationship)
    return stmt.where(_to_clause(tree))
