from __future__ import annotations

import sqlite3

from store.legacy_import import read_legacy_snapshot


def test_read_legacy_snapshot_preserves_mapping_and_parameter_data(tmp_path) -> None:
    source = tmp_path / "backend_db.sqlite3"
    connection = sqlite3.connect(source)
    connection.executescript(
        """
        CREATE TABLE order_params (
            id INTEGER PRIMARY KEY, item_id INTEGER, param_id INTEGER,
            user_data_id INTEGER, type TEXT, data TEXT, marketplace TEXT
        );
        CREATE TABLE param_value_mappings (
            id INTEGER PRIMARY KEY, type TEXT, label TEXT, value TEXT
        );
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY, email TEXT, email_normalized TEXT,
            ggsel_buyer_id TEXT, digiseller_buyer_id TEXT
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, marketplace TEXT, external_order_id TEXT,
            invoice_id TEXT, item_id INTEGER, options_json TEXT, amount REAL,
            currency TEXT, status TEXT, delivery_status INTEGER, chat_id TEXT,
            days_ordered INTEGER, remnawave_username TEXT, remnawave_uuid TEXT,
            subscription_url TEXT, customer_id INTEGER, created_at TEXT, updated_at TEXT
        );
        INSERT INTO order_params VALUES (1, 5422669, 10, 11, 'days', '30', 'digiseller');
        INSERT INTO param_value_mappings VALUES (1, 'days', '1 month', '30');
        INSERT INTO customers VALUES (7, 'buyer@example.com', 'buyer@example.com', 'buyer-7', NULL);
        INSERT INTO orders VALUES (
            8, 'ggsel', '991122', '440033', 5422669, '[]', 299.0,
            'RUB', 'paid', 1, '991122', 30, 'buyer-7', 'uuid-7',
            'https://example.test/sub', 7, '2026-07-01 12:00:00', '2026-07-01 12:01:00'
        );
        """
    )
    connection.commit()
    connection.close()

    snapshot = read_legacy_snapshot(source)

    assert snapshot["order_params"][0]["item_id"] == 5422669
    assert snapshot["order_params"][0]["marketplace"] == "digiseller"
    assert snapshot["param_value_mappings"][0] == {
        "id": 1, "type": "days", "label": "1 month", "value": "30"
    }
    assert snapshot["product_option_labels"] == []
    assert snapshot["customers"][0]["email"] == "buyer@example.com"
    assert snapshot["orders"][0]["invoice_id"] == "440033"
    assert snapshot["orders"][0]["external_order_id"] == "991122"
    assert snapshot["orders"][0]["delivery_status"] == 1
