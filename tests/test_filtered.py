from decimal import Decimal

import httpx


async def test_paid_orders_with_total_at_least_100_returns_alice(
    client: httpx.AsyncClient,
) -> None:
    payload = {
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

    response = await client.post("/filtered", json=payload)

    assert response.status_code == 200, response.text

    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 1

    row = rows[0]
    assert set(row.keys()) == {"orders"}

    order = row["orders"]
    assert order["customer_email"] == "alice@example.com"
    assert order["status"] == "paid"
    assert Decimal(order["total_amount"]) >= Decimal("100")
    assert order["currency"] == "USD"


async def test_non_cancelled_with_expensive_items_joins_alice_and_keyboard(
    client: httpx.AsyncClient,
) -> None:
    payload = {
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

    response = await client.post("/filtered", json=payload)

    assert response.status_code == 200, response.text

    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 1

    row = rows[0]
    assert set(row.keys()) == {"orders", "items"}

    order = row["orders"]
    assert order["customer_email"] == "alice@example.com"
    assert order["status"] != "cancelled"

    item = row["items"]
    assert item["order_id"] == order["id"]
    assert item["sku"] == "SKU-002"
    assert Decimal(item["unit_price"]) > Decimal("40")


async def test_paid_orders_joined_with_items_returns_all_alice_items(
    client: httpx.AsyncClient,
) -> None:
    payload = {
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
                    "op": "gt",
                    "table": "items",
                    "field": "quantity",
                    "value": 0,
                },
            ],
        },
    }

    response = await client.post("/filtered", json=payload)

    assert response.status_code == 200, response.text

    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 3

    for row in rows:
        assert set(row.keys()) == {"orders", "items"}
        assert row["orders"]["customer_email"] == "alice@example.com"
        assert row["orders"]["status"] == "paid"
        assert row["items"]["order_id"] == row["orders"]["id"]
        assert row["items"]["quantity"] > 0

    order_ids = {row["orders"]["id"] for row in rows}
    assert len(order_ids) == 1

    items_by_sku = {row["items"]["sku"]: row["items"] for row in rows}
    assert set(items_by_sku.keys()) == {"SKU-001", "SKU-002", "SKU-003"}
    assert items_by_sku["SKU-001"]["name"] == "Wireless Mouse"
    assert items_by_sku["SKU-002"]["name"] == "Mechanical Keyboard"
    assert items_by_sku["SKU-003"]["name"] == "USB-C Cable 1m"
    assert Decimal(items_by_sku["SKU-001"]["unit_price"]) == Decimal("29.99")
    assert Decimal(items_by_sku["SKU-002"]["unit_price"]) == Decimal("89.99")
    assert Decimal(items_by_sku["SKU-003"]["unit_price"]) == Decimal("9.99")


async def test_paid_orders_left_joined_with_items_keeps_orphan_order(
    client: httpx.AsyncClient,
) -> None:
    payload = {
        "table": "orders",
        "joins": {"items": "left"},
        "filter": {
            "op": "eq",
            "table": "orders",
            "field": "status",
            "value": "paid",
        },
    }

    response = await client.post("/filtered", json=payload)

    assert response.status_code == 200, response.text

    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 4

    for row in rows:
        assert set(row.keys()) == {"orders", "items"}
        assert row["orders"]["status"] == "paid"

    alice_rows = [
        row
        for row in rows
        if row["orders"]["customer_email"] == "alice@example.com"
    ]
    eve_rows = [
        row
        for row in rows
        if row["orders"]["customer_email"] == "eve@example.com"
    ]

    assert len(alice_rows) == 3
    assert len(eve_rows) == 1

    alice_items_by_sku = {
        row["items"]["sku"]: row["items"] for row in alice_rows
    }
    assert set(alice_items_by_sku.keys()) == {"SKU-001", "SKU-002", "SKU-003"}
    for item in alice_items_by_sku.values():
        assert item["order_id"] == alice_rows[0]["orders"]["id"]

    [eve_row] = eve_rows
    assert eve_row["items"] is None
    assert Decimal(eve_row["orders"]["total_amount"]) == Decimal("75.00")
