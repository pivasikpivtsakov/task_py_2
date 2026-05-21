from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from schema.rows import ItemsRow, OrdersRow


@dataclass(frozen=True)
class JoinSpec:
    self_column: str
    other_column: str


@dataclass(frozen=True)
class TableSpec:
    row_model: type[BaseModel]
    joins: Mapping[str, JoinSpec]

    @property
    def columns(self) -> frozenset[str]:
        return frozenset(self.row_model.model_fields)


TABLE_REGISTRY: dict[str, TableSpec] = {
    "orders": TableSpec(
        row_model=OrdersRow,
        joins={"items": JoinSpec(self_column="id", other_column="order_id")},
    ),
    "items": TableSpec(
        row_model=ItemsRow,
        joins={"orders": JoinSpec(self_column="order_id", other_column="id")},
    ),
}
