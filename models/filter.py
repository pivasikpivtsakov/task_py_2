from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from models.db import TABLE_REGISTRY, TableSpec
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

_JOIN_SQL: dict[JoinType, str] = {
    "inner": "INNER JOIN",
    "left": "LEFT JOIN",
}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: tuple[Any, ...]


def _quote(name: str) -> str:
    # reject anything that could break out of the double-quoted identifier
    if '"' in name or "\x00" in name:
        msg = f"invalid identifier '{name}'"
        raise ValueError(msg)
    return f'"{name}"'


def _qualified(table: str, column: str) -> str:
    return f"{_quote(table)}.{_quote(column)}"


def _collect_references(node: FilterNodeSchema) -> set[tuple[str, str]]:
    # internal node: union refs from all children
    if isinstance(node, LogicalNodeSchema):
        return {
            ref
            for child in node.children
            for ref in _collect_references(child)
        }
    # leaf: single (table, field) reference
    return {(node.table, node.field)}


@dataclass(frozen=True)
class _QueryPlan:
    primary_table: str
    primary_spec: TableSpec
    related: list[str]
    join_type_overrides: Mapping[str, JoinType]


def _plan_query(
    *,
    primary_table: str,
    tree: FilterNodeSchema,
    joins: Mapping[str, JoinType] | None,
) -> _QueryPlan:
    join_type_overrides: Mapping[str, JoinType] = (
        joins if joins is not None else {}
    )

    if primary_table not in TABLE_REGISTRY:
        msg = f"unknown primary table '{primary_table}'"
        raise ValueError(msg)
    # join type only makes sense for non-primary tables
    if primary_table in join_type_overrides:
        msg = f"cannot declare a join for the primary table '{primary_table}'"
        raise ValueError(msg)

    references = _collect_references(tree)
    referenced_tables = {table for table, _ in references}
    # everything used in filters or overrides, minus the primary itself
    related = sorted(
        (referenced_tables | set(join_type_overrides)) - {primary_table},
    )

    primary_spec = TABLE_REGISTRY[primary_table]
    for table in related:
        if table not in TABLE_REGISTRY:
            msg = f"unknown table '{table}'"
            raise ValueError(msg)
        # joinability is declared statically in the registry
        if table not in primary_spec.joins:
            msg = (
                f"no relationship from '{primary_table}' to '{table}'; "
                f"declare one in TABLE_REGISTRY to make it joinable"
            )
            raise ValueError(msg)

    # column existence check for every (table, field) used in the tree
    for table, field in references:
        if field not in TABLE_REGISTRY[table].columns:
            msg = f"unknown field '{table}.{field}'"
            raise ValueError(msg)

    return _QueryPlan(
        primary_table=primary_table,
        primary_spec=primary_spec,
        related=related,
        join_type_overrides=join_type_overrides,
    )


_ALIAS_SEP = "__"


def _alias_for(table: str, column: str) -> str:
    return f"{table}{_ALIAS_SEP}{column}"


def _split_alias(alias: str) -> tuple[str, str]:
    table, column = alias.split(_ALIAS_SEP, 1)
    return table, column


def _aliased_column(table: str, column: str) -> str:
    return (
        f"{_qualified(table, column)} AS {_quote(_alias_for(table, column))}"
    )


def _build_select(plan: _QueryPlan) -> str:
    # primary first, then related; sorted columns give stable output
    columns: list[str] = [
        _aliased_column(table, column)
        for table in [plan.primary_table, *plan.related]
        for column in sorted(TABLE_REGISTRY[table].columns)
    ]
    return f"SELECT {', '.join(columns)}"


def _build_from(plan: _QueryPlan) -> str:
    return f"FROM {_quote(plan.primary_table)}"


def _build_joins(plan: _QueryPlan) -> str:
    join_clauses: list[str] = []
    for table in plan.related:
        join_spec = plan.primary_spec.joins[table]
        # default to INNER JOIN unless caller overrides per table
        keyword = _JOIN_SQL[plan.join_type_overrides.get(table, "inner")]
        join_clauses.append(
            f"{keyword} {_quote(table)} "
            f"ON {_qualified(table, join_spec.other_column)} "
            f"= {_qualified(plan.primary_table, join_spec.self_column)}"
        )
    return "\n".join(join_clauses)


def _build_where_expr(node: FilterNodeSchema, params: list[Any]) -> str:
    # branch node: recurse into each child, then glue with AND/OR
    if isinstance(node, LogicalNodeSchema):
        joiner = " AND " if node.op == "and" else " OR "
        # parens preserve precedence when this is itself a child
        rendered = joiner.join(
            _build_where_expr(child, params) for child in node.children
        )
        return f"({rendered})"

    # leaf node from here on: render a single comparison against col
    col = _qualified(node.table, node.field)

    # multi-value leaf: bind every element, render IN/NOT IN
    if node.op in ("in", "nin"):
        values = node.value
        assert isinstance(values, list)
        # short-circuit before touching params:
        # empty IN never matches, empty NOT IN always matches
        if not values:
            return "FALSE" if node.op == "in" else "TRUE"
        placeholders: list[str] = []
        # each iteration appends to params and emits the $N placeholder
        for value in values:
            params.append(value)
            placeholders.append(f"${len(params)}")
        keyword = "IN" if node.op == "in" else "NOT IN"
        return f"{col} {keyword} ({', '.join(placeholders)})"

    # NULL leaf: no placeholder bound, NULL must use IS / IS NOT
    if node.value is None and node.op in ("eq", "ne"):
        return f"{col} IS{' NOT' if node.op == 'ne' else ''} NULL"

    # scalar leaf: bind one value, emit one placeholder
    params.append(node.value)
    return f"{col} {_COMPARISON_SQL[node.op]} ${len(params)}"


def _build_where(tree: FilterNodeSchema, params: list[Any]) -> str:
    return f"WHERE {_build_where_expr(tree, params)}"


def compile_filter(
    *,
    primary_table: str,
    tree: FilterNodeSchema,
    joins: Mapping[str, JoinType] | None = None,
) -> CompiledQuery:
    plan = _plan_query(primary_table=primary_table, tree=tree, joins=joins)

    # _build_where appends placeholders to params as it walks the tree
    params: list[Any] = []
    clauses: list[str] = [
        _build_select(plan),
        _build_from(plan),
        _build_joins(plan),
        _build_where(tree, params),
    ]
    # drop empty clauses (e.g. no joins) so the SQL has no blank lines
    return CompiledQuery(
        sql="\n".join(c for c in clauses if c),
        params=tuple(params),
    )


def _is_orphan_row(fields: Mapping[str, Any]) -> bool:
    # a LEFT JOIN miss makes every column of the absent row NULL
    return all(value is None for value in fields.values())


def decode_record(
    record: Mapping[str, Any],
) -> dict[str, dict[str, Any] | None]:
    grouped: dict[str, dict[str, Any]] = {}
    # undo "table__column" aliasing and bucket fields back per table
    for alias, value in record.items():
        table, column = _split_alias(alias)
        grouped.setdefault(table, {})[column] = value

    decoded: dict[str, dict[str, Any] | None] = {}
    for table, fields in grouped.items():
        # missing left-joined row collapses to None
        if _is_orphan_row(fields):
            decoded[table] = None
        else:
            # validate through the table's pydantic row model before exposing
            decoded[table] = (
                TABLE_REGISTRY[table]
                .row_model.model_validate(fields)
                .model_dump()
            )
    return decoded
