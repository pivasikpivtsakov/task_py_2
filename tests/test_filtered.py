import httpx


async def test_paid_orders_with_total_at_least_100_returns_alice(client: httpx.AsyncClient) -> None:
    payload = {
        "table": "orders",
        "filter": {
            "op": "and",
            "children": [
                {"op": "eq", "table": "orders", "field": "status", "value": "paid"},
                {"op": "gte", "table": "orders", "field": "total_amount", "value": 100},
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
    assert float(order["total_amount"]) >= 100
    assert order["currency"] == "USD"
