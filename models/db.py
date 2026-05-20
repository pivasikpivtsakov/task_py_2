from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')",
            name="orders_status_check",
        ),
        CheckConstraint("total_amount >= 0", name="orders_total_amount_check"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    customer_email: Mapped[str] = mapped_column(index=True)
    customer_name: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="pending", server_default="pending", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    note: Mapped[str | None]
    created_dt: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    updated_dt: Mapped[datetime] = mapped_column(server_default=func.now())

    items: Mapped[list["Item"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="items_quantity_check"),
        CheckConstraint("unit_price >= 0", name="items_unit_price_check"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
    )
    sku: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_dt: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_dt: Mapped[datetime] = mapped_column(server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="items")


class Filter(Base):
    __tablename__ = "filters"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    filter_rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_dt: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_dt: Mapped[datetime] = mapped_column(server_default=func.now())


TABLE_REGISTRY: dict[str, type[Base]] = {
    mapper.class_.__tablename__: mapper.class_
    for mapper in Base.registry.mappers
}
