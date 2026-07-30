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
        INSERT INTO order_params VALUES (1, 5422669, 10, 11, 'days', '30', 'digiseller');
        INSERT INTO param_value_mappings VALUES (1, 'days', '1 month', '30');
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
