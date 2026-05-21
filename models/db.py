from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class JoinSpec:
    self_column: str
    other_column: str


@dataclass(frozen=True)
class TableSpec:
    columns: frozenset[str]
    joins: Mapping[str, JoinSpec]


TABLE_REGISTRY: dict[str, TableSpec] = {
    "orders": TableSpec(
        columns=frozenset({
            "id", "customer_email", "customer_name", "status",
            "total_amount", "currency", "note", "created_dt", "updated_dt",
        }),
        joins={"items": JoinSpec(self_column="id", other_column="order_id")},
    ),
    "items": TableSpec(
        columns=frozenset({
            "id", "order_id", "sku", "name", "quantity",
            "unit_price", "created_dt", "updated_dt",
        }),
        joins={"orders": JoinSpec(self_column="order_id", other_column="id")},
    ),
    "filters": TableSpec(
        columns=frozenset({"id", "filter_rules", "created_dt", "updated_dt"}),
        joins={},
    ),
}
