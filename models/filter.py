from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from models.db import TABLE_REGISTRY
from schema.filter import (
    ComparisonOp,
    FilterNodeSchema,
    JoinType,
    LogicalNodeSchema,
)

_COMPARISON_SQL: dict[ComparisonOp, str] = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: tuple[Any, ...]


def _quote(name: str) -> str:
    if '"' in name or "\x00" in name:
        raise ValueError(f"invalid identifier '{name}'")
    return f'"{name}"'


def _collect_tables(node: FilterNodeSchema) -> set[str]:
    if isinstance(node, LogicalNodeSchema):
        return {t for child in node.children for t in _collect_tables(child)}
    return {node.table}


def _build_where(node: FilterNodeSchema, params: list[Any]) -> str:
    if isinstance(node, LogicalNodeSchema):
        joiner = " AND " if node.op == "and" else " OR "
        return "(" + joiner.join(_build_where(c, params) for c in node.children) + ")"

    if node.table not in TABLE_REGISTRY:
        raise ValueError(f"unknown table '{node.table}'")
    if node.field not in TABLE_REGISTRY[node.table].columns:
        raise ValueError(f"unknown field '{node.table}.{node.field}'")
    col = f"{_quote(node.table)}.{_quote(node.field)}"

    if node.op in ("in", "nin"):
        values = node.value
        assert isinstance(values, list)
        if not values:
            return "FALSE" if node.op == "in" else "TRUE"
        placeholders = []
        for v in values:
            params.append(v)
            placeholders.append(f"${len(params)}")
        keyword = "IN" if node.op == "in" else "NOT IN"
        return f"{col} {keyword} ({', '.join(placeholders)})"

    if node.value is None and node.op in ("eq", "ne"):
        return f"{col} IS{' NOT' if node.op == 'ne' else ''} NULL"

    params.append(node.value)
    return f"{col} {_COMPARISON_SQL[node.op]} ${len(params)}"


def compile_filter(
    *,
    primary_table: str,
    tree: FilterNodeSchema,
    joins: Mapping[str, JoinType] | None = None,
) -> CompiledQuery:
    if primary_table not in TABLE_REGISTRY:
        raise ValueError(f"unknown primary table '{primary_table}'")
    joins = joins or {}
    if primary_table in joins:
        raise ValueError(f"cannot declare a join for the primary table '{primary_table}'")

    related = sorted((_collect_tables(tree) - {primary_table}) | joins.keys())
    unknown = [t for t in related if t not in TABLE_REGISTRY]
    if unknown:
        raise ValueError(f"unknown tables: {unknown}")

    primary_spec = TABLE_REGISTRY[primary_table]
    selects = [f"to_jsonb({_quote(primary_table)}) AS {_quote(primary_table)}"]
    join_clauses: list[str] = []
    for t in related:
        if t not in primary_spec.joins:
            raise ValueError(
                f"no relationship from '{primary_table}' to '{t}'; "
                f"declare one in TABLE_REGISTRY to make it joinable"
            )
        js = primary_spec.joins[t]
        keyword = "LEFT JOIN" if joins.get(t, "inner") == "left" else "INNER JOIN"
        join_clauses.append(
            f"{keyword} {_quote(t)} "
            f"ON {_quote(t)}.{_quote(js.other_column)} = {_quote(primary_table)}.{_quote(js.self_column)}"
        )
        selects.append(
            f"CASE WHEN {_quote(t)} IS NULL THEN NULL "
            f"ELSE to_jsonb({_quote(t)}) END AS {_quote(t)}"
        )

    params: list[Any] = []
    where_sql = _build_where(tree, params)

    sql = "\n".join([
        f"SELECT {', '.join(selects)}",
        f"FROM {_quote(primary_table)}",
        *join_clauses,
        f"WHERE {where_sql}",
    ])
    return CompiledQuery(sql=sql, params=tuple(params))
