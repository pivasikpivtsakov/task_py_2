"""
Filter shape reference.

A filter request targets one primary table and carries a tree of nodes.
The compiler (models.filter.compile_filter) takes the primary table plus
the tree, auto-joins any related tables referenced by comparison nodes
(via SQLAlchemy relationships declared in models.db), and emits a single
SELECT.

Top-level shape:
    {
        "table": "<primary table name>",   # FROM table
        "filter": <FilterNodeSchema>       # tree of and/or/comparison nodes
    }

Node types:
    LogicalNodeSchema:
        {"op": "and" | "or", "children": [<FilterNodeSchema>, ...]}
    ComparisonNodeSchema:
        {
            "op": <ComparisonOp>,
            "table": "<tname>",
            "field": "<fname>",
            "value": <scalar | [scalars]>,
        }

Comparison ops:
    "eq", "ne", "gt", "gte", "lt", "lte"   -> scalar value
    "in",  "nin"                            -> list value

Cross-table semantics:
    Any comparison node may target a table other than the primary, as long
    as the SQLAlchemy model for the primary declares a relationship to that
    table. The compiler emits an INNER JOIN; result rows are
    (primary, related) tuples — orders with multiple matching items appear
    multiple times, orders with no matching items don't appear.

Examples:

    # single-table: paid orders with total >= 100
    {
        "table": "orders",
        "filter": {
            "op": "and",
            "children": [
                {
                    "op": "eq",
                    "table": "orders",
                    "field": "status",
                    "value": "paid",
                },
                {
                    "op": "gte",
                    "table": "orders",
                    "field": "total_amount",
                    "value": 100,
                },
            ],
        },
    }

    # cross-table: non-cancelled orders with an item with unit_price > 40
    {
        "table": "orders",
        "filter": {
            "op": "and",
            "children": [
                {
                    "op": "ne",
                    "table": "orders",
                    "field": "status",
                    "value": "cancelled",
                },
                {
                    "op": "gt",
                    "table": "items",
                    "field": "unit_price",
                    "value": 40,
                },
            ],
        },
    }

    # items only with IN list
    {
        "table": "items",
        "filter": {
            "op": "in", "table": "items", "field": "sku",
            "value": ["SKU-002", "SKU-011", "SKU-030"]
        }
    }
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Scalar = bool | int | Decimal | str | None
ComparisonOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"]
LogicalOp = Literal["and", "or"]
JoinType = Literal["inner", "left"]

_LIST_OPS: frozenset[str] = frozenset({"in", "nin"})


class ComparisonNodeSchema(BaseModel):
    op: ComparisonOp
    table: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def _check_value_shape(self) -> "ComparisonNodeSchema":
        is_list_value = isinstance(self.value, list)
        if self.op in _LIST_OPS and not is_list_value:
            msg = f"op '{self.op}' requires a list value"
            raise ValueError(msg)
        if self.op not in _LIST_OPS and is_list_value:
            msg = f"op '{self.op}' requires a scalar value"
            raise ValueError(msg)
        return self


class LogicalNodeSchema(BaseModel):
    op: LogicalOp
    children: list["FilterNodeSchema"] = Field(min_length=1)


FilterNodeSchema = Annotated[
    LogicalNodeSchema | ComparisonNodeSchema,
    Field(discriminator="op"),
]

LogicalNodeSchema.model_rebuild()


class FilteredRequest(BaseModel):
    table: str = Field(min_length=1)
    filter: FilterNodeSchema
    joins: dict[str, JoinType] = Field(default_factory=dict)
