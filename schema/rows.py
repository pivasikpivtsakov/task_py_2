from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OrdersRow(BaseModel):
    id: int
    customer_email: str
    customer_name: str | None
    status: str
    total_amount: Decimal
    currency: str
    note: str | None
    created_dt: datetime
    updated_dt: datetime


class ItemsRow(BaseModel):
    id: int
    order_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    created_dt: datetime
    updated_dt: datetime
