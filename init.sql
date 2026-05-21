drop table if exists items   cascade;
drop table if exists orders  cascade;
drop table if exists filters cascade;
drop function if exists set_updated_dt cascade;


create function set_updated_dt()
returns trigger
language plpgsql
as $$
begin
    new.updated_dt := now();
    return new;
end;
$$;


create table filters (
    id           bigint      generated always as identity primary key,
    filter_rules jsonb       not null,
    created_dt   timestamptz not null default now(),
    updated_dt   timestamptz not null default now()
);

create trigger filters_set_updated_dt
    before update on filters
    for each row
    when (old.* is distinct from new.*)
    execute function set_updated_dt();


create table orders (
    id             bigint         generated always as identity primary key,
    customer_email text           not null,
    customer_name  text,
    status         text           not null default 'pending'
        check (status in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')),
    total_amount   numeric(12, 2) not null default 0 check (total_amount >= 0),
    currency       char(3)        not null default 'USD',
    note           text,
    created_dt     timestamptz    not null default now(),
    updated_dt     timestamptz    not null default now()
);

create index orders_customer_email_idx on orders (customer_email);
create index orders_status_idx         on orders (status);
create index orders_created_dt_idx     on orders (created_dt desc);

create trigger orders_set_updated_dt
    before update on orders
    for each row
    when (old.* is distinct from new.*)
    execute function set_updated_dt();


create table items (
    id         bigint         generated always as identity primary key,
    order_id   bigint         not null references orders (id) on delete cascade,
    sku        text           not null,
    name       text           not null,
    quantity   integer        not null check (quantity > 0),
    unit_price numeric(12, 2) not null check (unit_price >= 0),
    created_dt timestamptz    not null default now(),
    updated_dt timestamptz    not null default now()
);

create index items_order_id_idx on items (order_id);
create index items_sku_idx      on items (sku);

create trigger items_set_updated_dt
    before update on items
    for each row
    when (old.* is distinct from new.*)
    execute function set_updated_dt();


insert into filters (filter_rules) values
    ('{
        "table": "orders",
        "filter": {
            "op": "and",
            "children": [
                {"op": "eq",  "table": "orders", "field": "status",       "value": "paid"},
                {"op": "gte", "table": "orders", "field": "total_amount", "value": 100}
            ]
        }
    }'::jsonb),
    ('{
        "table": "orders",
        "filter": {
            "op": "and",
            "children": [
                {"op": "ne", "table": "orders", "field": "status",     "value": "cancelled"},
                {"op": "gt", "table": "items",  "field": "unit_price", "value": 40}
            ]
        }
    }'::jsonb),
    ('{
        "table": "items",
        "filter": {
            "op": "in", "table": "items", "field": "sku",
            "value": ["SKU-002", "SKU-011", "SKU-030"]
        }
    }'::jsonb);


with new_orders as (
    insert into orders (customer_email, customer_name, status, total_amount, currency, note) values
        ('alice@example.com', 'Alice Johnson',  'paid',      129.97, 'USD', 'gift wrap please'),
        ('bob@example.com',   'Bob Smith',      'shipped',    49.50, 'USD', null),
        ('carol@example.com', 'Carol Martinez', 'pending',    15.00, 'EUR', null),
        ('dave@example.com',  'Dave Wilson',    'cancelled',   0.00, 'USD', 'duplicate order'),
        ('eve@example.com',   'Eve Davis',      'paid',       75.00, 'USD', 'no items yet')
    returning id, customer_email
)
insert into items (order_id, sku, name, quantity, unit_price)
select o.id, v.sku, v.name, v.quantity, v.unit_price
from new_orders o
join (values
    ('alice@example.com', 'SKU-001', 'Wireless Mouse',      1,  29.99),
    ('alice@example.com', 'SKU-002', 'Mechanical Keyboard', 1,  89.99),
    ('alice@example.com', 'SKU-003', 'USB-C Cable 1m',      1,   9.99),
    ('bob@example.com',   'SKU-010', 'Notebook A5',         3,   5.50),
    ('bob@example.com',   'SKU-011', 'Pen Pack (10)',       2,  16.50),
    ('carol@example.com', 'SKU-020', 'Coffee Mug',          1,  15.00),
    ('dave@example.com',  'SKU-030', 'Desk Lamp',           1,  45.00)
) as v(customer_email, sku, name, quantity, unit_price)
    on v.customer_email = o.customer_email;
