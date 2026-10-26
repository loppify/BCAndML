"""Local SQLite repository for off-chain payloads and an event-log mirror."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS device_metadata (
                    device_id TEXT PRIMARY KEY,
                    local_name TEXT NOT NULL,
                    owner_address TEXT NOT NULL,
                    metadata_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS flow_records (
                    flow_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES device_metadata(device_id),
                    input_hash TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    feature_schema TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    raw_data_ref TEXT,
                    label INTEGER CHECK (label IN (0, 1) OR label IS NULL)
                );
                CREATE INDEX IF NOT EXISTS ix_flow_input_hash ON flow_records(input_hash);
                CREATE INDEX IF NOT EXISTS ix_flow_device_time ON flow_records(device_id, observed_at);
                CREATE TABLE IF NOT EXISTS model_artifacts (
                    version INTEGER PRIMARY KEY,
                    artifact_path TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL UNIQUE,
                    feature_schema TEXT NOT NULL,
                    threshold_bps INTEGER NOT NULL CHECK (threshold_bps BETWEEN 0 AND 10000),
                    trained_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flow_records(flow_id),
                    device_id TEXT NOT NULL REFERENCES device_metadata(device_id),
                    model_version INTEGER NOT NULL REFERENCES model_artifacts(version),
                    input_hash TEXT NOT NULL,
                    is_attack INTEGER NOT NULL CHECK (is_attack IN (0, 1)),
                    confidence_bps INTEGER NOT NULL CHECK (confidence_bps BETWEEN 0 AND 10000),
                    tx_hash TEXT,
                    block_number INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_predictions_device_time ON predictions(device_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_predictions_flow ON predictions(flow_id);
                CREATE TABLE IF NOT EXISTS chain_event_mirror (
                    tx_hash TEXT NOT NULL,
                    log_index INTEGER NOT NULL,
                    event_name TEXT NOT NULL,
                    device_id TEXT,
                    model_version INTEGER,
                    block_number INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    PRIMARY KEY (tx_hash, log_index)
                );
            """)

    def save_device(self, device_id: str, local_name: str, owner: str, metadata_hash: str) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO device_metadata(device_id, local_name, owner_address, metadata_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET local_name=excluded.local_name,
                     owner_address=excluded.owner_address, metadata_hash=excluded.metadata_hash""",
                (device_id.lower(), local_name, owner.lower(), metadata_hash.lower(), utc_now()),
            )

    def device(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM device_metadata WHERE device_id=?", (device_id.lower(),)).fetchone()
        return dict(row) if row else None

    def devices(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM device_metadata ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def save_model(self, version: int, artifact_path: str, artifact_hash: str,
                   feature_schema: str, threshold_bps: int, metrics: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO model_artifacts(version, artifact_path, artifact_hash, feature_schema,
                   threshold_bps, trained_at, metrics_json) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(version) DO UPDATE SET artifact_path=excluded.artifact_path,
                     artifact_hash=excluded.artifact_hash, feature_schema=excluded.feature_schema,
                     threshold_bps=excluded.threshold_bps, trained_at=excluded.trained_at,
                     metrics_json=excluded.metrics_json""",
                (version, artifact_path, artifact_hash.lower(), feature_schema, threshold_bps,
                 utc_now(), json.dumps(metrics, ensure_ascii=False, sort_keys=True)),
            )

    def save_flow(self, flow_id: str, device_id: str, input_hash: str, observed_at: str,
                  features: dict[str, Any], raw_data_ref: str | None = None,
                  label: int | None = None) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO flow_records(flow_id, device_id, input_hash, observed_at,
                   feature_schema, features_json, raw_data_ref, label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (flow_id, device_id.lower(), input_hash.lower(), observed_at, "ton_iot_numeric_v1",
                 json.dumps(features, ensure_ascii=False, sort_keys=True), raw_data_ref, label),
            )

    def save_prediction(self, prediction_id: str, flow_id: str, device_id: str, model_version: int,
                        input_hash: str, is_attack: bool, confidence_bps: int,
                        tx_hash: str | None = None, block_number: int | None = None,
                        status: str = "pending") -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO predictions(prediction_id, flow_id, device_id, model_version,
                   input_hash, is_attack, confidence_bps, tx_hash, block_number, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prediction_id, flow_id, device_id.lower(), model_version, input_hash.lower(),
                 int(is_attack), confidence_bps, tx_hash.lower() if tx_hash else None,
                 block_number, status, utc_now()),
            )

    def prediction_for_flow(self, flow_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM predictions WHERE flow_id=?", (flow_id,)).fetchone()
        return dict(row) if row else None

    def prediction(self, prediction_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
        return dict(row) if row else None

    def update_prediction_chain(self, prediction_id: str, tx_hash: str, block_number: int, status: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE predictions SET tx_hash=?, block_number=?, status=? WHERE prediction_id=?",
                (tx_hash.lower(), block_number, status, prediction_id),
            )

    def prediction_payload(self, flow_id: str) -> tuple[dict[str, Any], str] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM flow_records WHERE flow_id=?", (flow_id,)).fetchone()
        if row is None:
            return None
        payload = {
            "flow_id": row["flow_id"],
            "device_id": row["device_id"],
            "observed_at": row["observed_at"],
            "schema_version": row["feature_schema"],
            "features": json.loads(row["features_json"]),
        }
        return payload, str(row["input_hash"])

    def update_prediction_status(self, prediction_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE predictions SET status=? WHERE prediction_id=?", (status, prediction_id))

    def refresh_events(self, events: list[dict[str, Any]]) -> None:
        with self.connect() as db:
            for event in events:
                db.execute(
                    """INSERT INTO chain_event_mirror(tx_hash, log_index, event_name, device_id,
                       model_version, block_number, payload_json, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(tx_hash, log_index) DO UPDATE SET event_name=excluded.event_name,
                         device_id=excluded.device_id, model_version=excluded.model_version,
                         block_number=excluded.block_number, payload_json=excluded.payload_json,
                         indexed_at=excluded.indexed_at""",
                    (event["tx_hash"].lower(), int(event["log_index"]), event["event_name"],
                     (event.get("device_id") or "").lower() or None, event.get("model_version"),
                     int(event["block_number"]), json.dumps(event, ensure_ascii=False, sort_keys=True), utc_now()),
                )

    def event_mirror_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM chain_event_mirror").fetchone()
        return int(row["count"])

    def predictions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM predictions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
