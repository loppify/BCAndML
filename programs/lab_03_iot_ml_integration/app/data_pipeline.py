"""Deterministic ToN_IoT ingestion, cleaning and group-aware partitioning."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


RANDOM_SEED = 42
FEATURES = [
    "src_port", "dst_port", "duration", "src_bytes", "dst_bytes",
    "missed_bytes", "src_pkts", "src_ip_bytes", "dst_pkts", "dst_ip_bytes",
    "dns_qclass", "dns_qtype", "dns_rcode", "http_request_body_len",
    "http_response_body_len", "http_status_code",
]
FORBIDDEN_MODEL_FIELDS = {"src_ip", "dst_ip", "label", "type"}
SIGNATURE_PORTS = {23, 2323, 3389, 7547}


@dataclass
class DataPartitions:
    frame: pd.DataFrame
    train_index: np.ndarray
    validation_index: np.ndarray
    test_index: np.ndarray
    split_info: dict[str, Any]

    @property
    def train(self) -> pd.DataFrame:
        return self.frame.iloc[self.train_index]

    @property
    def validation(self) -> pd.DataFrame:
        return self.frame.iloc[self.validation_index]

    @property
    def test(self) -> pd.DataFrame:
        return self.frame.iloc[self.test_index]


def load_clean_data(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {path}")
    raw = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    required = set(FEATURES) | {"label", "src_ip", "type", "conn_state"}
    missing = sorted(required.difference(raw.columns))
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(missing)}")

    loaded_rows = len(raw)
    duplicate_rows = int(raw.duplicated().sum())
    data = raw.drop_duplicates().reset_index(drop=True)
    original_missing = int(data[FEATURES].isna().sum().sum())
    data[FEATURES] = data[FEATURES].apply(pd.to_numeric, errors="coerce")
    data[FEATURES] = data[FEATURES].replace([np.inf, -np.inf], np.nan)
    numeric_missing = int(data[FEATURES].isna().sum().sum())
    labels = pd.to_numeric(data["label"], errors="coerce")
    if labels.isna().any() or not set(labels.unique()).issubset({0, 1}):
        raise ValueError("The binary label column must contain only 0 and 1.")
    if data["src_ip"].isna().any():
        raise ValueError("Source IP group keys are required for leakage-safe splitting.")
    data["label"] = labels.astype("int8")
    data["src_ip"] = data["src_ip"].astype(str)
    data["conn_state"] = data["conn_state"].fillna("").astype(str)
    data["dst_port"] = data["dst_port"].fillna(-1)
    data["src_pkts"] = data["src_pkts"].fillna(0)

    if set(FEATURES).intersection(FORBIDDEN_MODEL_FIELDS):
        raise AssertionError("Label, type and IP fields must not enter the model schema.")

    info = {
        "source_file": path.name,
        "rows_loaded": loaded_rows,
        "columns_loaded": len(raw.columns),
        "duplicates_removed": duplicate_rows,
        "rows_after_deduplication": len(data),
        "missing_values_before_imputation": original_missing,
        "nonfinite_or_nonnumeric_values_converted_to_missing": max(0, numeric_missing - original_missing),
        "missing_feature_cells_to_impute": numeric_missing,
        "class_counts": {str(int(k)): int(v) for k, v in data["label"].value_counts().sort_index().items()},
        "source_groups": int(data["src_ip"].nunique()),
        "feature_names": FEATURES,
        "excluded_fields": sorted(FORBIDDEN_MODEL_FIELDS),
        "random_seed": RANDOM_SEED,
    }
    return data, info


def _valid_stratified_split(frame: pd.DataFrame, n_splits: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    X = frame[FEATURES]
    y = frame["label"]
    groups = frame["src_ip"]
    candidates = list(splitter.split(X, y, groups))
    target_prevalence = float(y.mean())
    valid = []
    for train_index, held_index in candidates:
        if set(y.iloc[train_index].unique()) == {0, 1} and set(y.iloc[held_index].unique()) == {0, 1}:
            held_prevalence = float(y.iloc[held_index].mean())
            held_fraction = len(held_index) / len(y)
            score = abs(held_prevalence - target_prevalence) + 0.25 * abs(held_fraction - 1 / n_splits)
            valid.append((score, train_index, held_index))
    if not valid:
        raise ValueError("Could not construct disjoint train and held-out groups containing both classes.")
    _, train_index, held_index = min(valid, key=lambda candidate: candidate[0])
    return np.asarray(train_index), np.asarray(held_index)


def make_partitions(frame: pd.DataFrame) -> DataPartitions:
    outer_train_index, test_index = _valid_stratified_split(frame, n_splits=5, seed=RANDOM_SEED)
    outer_train = frame.iloc[outer_train_index].reset_index(drop=False).rename(columns={"index": "_source_index"})
    inner_train_relative, validation_relative = _valid_stratified_split(
        outer_train, n_splits=5, seed=RANDOM_SEED + 1
    )
    train_index = outer_train.iloc[inner_train_relative]["_source_index"].to_numpy(dtype=int)
    validation_index = outer_train.iloc[validation_relative]["_source_index"].to_numpy(dtype=int)
    test_index = frame.index.to_numpy(dtype=int)[test_index]

    train_groups = set(frame.iloc[train_index]["src_ip"])
    validation_groups = set(frame.iloc[validation_index]["src_ip"])
    test_groups = set(frame.iloc[test_index]["src_ip"])
    overlap = {
        "train_validation": sorted(train_groups & validation_groups),
        "train_test": sorted(train_groups & test_groups),
        "validation_test": sorted(validation_groups & test_groups),
    }
    if any(overlap.values()):
        raise AssertionError(f"Source IP leakage detected: {overlap}")

    info = {
        "train_rows": int(len(train_index)),
        "validation_rows": int(len(validation_index)),
        "test_rows": int(len(test_index)),
        "train_groups": int(len(train_groups)),
        "validation_groups": int(len(validation_groups)),
        "test_groups": int(len(test_groups)),
        "group_overlap_counts": {name: len(values) for name, values in overlap.items()},
        "train_class_counts": {str(int(k)): int(v) for k, v in frame.iloc[train_index]["label"].value_counts().sort_index().items()},
        "validation_class_counts": {str(int(k)): int(v) for k, v in frame.iloc[validation_index]["label"].value_counts().sort_index().items()},
        "test_class_counts": {str(int(k)): int(v) for k, v in frame.iloc[test_index]["label"].value_counts().sort_index().items()},
    }
    return DataPartitions(frame, train_index, validation_index, test_index, info)


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_flow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = {"flow_id", "device_id", "observed_at", "schema_version", "features"}
    if set(payload) != required:
        raise ValueError("Canonical flow payload must contain only flow_id, device_id, observed_at, schema_version and features.")
    features = payload["features"]
    if not isinstance(features, dict) or set(features) != set(FEATURES):
        raise ValueError("Canonical payload features do not match the model feature schema.")
    normalized_features: dict[str, float | None] = {}
    for name in FEATURES:
        value = features[name]
        if value is None:
            normalized_features[name] = None
        else:
            number = float(value)
            if not np.isfinite(number):
                raise ValueError(f"Feature {name} must be a finite number or null.")
            normalized_features[name] = number
    return {
        "flow_id": str(payload["flow_id"]),
        "device_id": str(payload["device_id"]).lower(),
        "observed_at": str(payload["observed_at"]),
        "schema_version": str(payload["schema_version"]),
        "features": normalized_features,
    }


def sha256_hex(payload: bytes) -> str:
    return "0x" + hashlib.sha256(payload).hexdigest()


def signature_prediction(dst_port: float, src_pkts: float, conn_state: str) -> int:
    return int(
        int(dst_port) in SIGNATURE_PORTS
        or (conn_state in {"S0", "REJ"} and float(src_pkts) >= 100)
    )


def make_demo_flows(partitions: DataPartitions, max_per_class: int = 6, model=None) -> list[dict[str, Any]]:
    test = partitions.test
    samples: list[dict[str, Any]] = []
    sequence = 0
    for label in (0, 1):
        subset = test.loc[test["label"] == label]
        if model is not None and len(subset):
            probabilities = model.predict_proba(subset[FEATURES])[:, list(model.named_steps["classifier"].classes_).index(1)]
            predictions = (probabilities >= 0.5).astype("int8")
            subset = subset.loc[predictions == label]
        # Select varied values deterministically across the held-out rows.
        if len(subset) > max_per_class:
            positions = np.linspace(0, len(subset) - 1, max_per_class, dtype=int)
            subset = subset.iloc[positions]
        for number, (_, row) in enumerate(subset.iterrows(), start=1):
            sequence += 1
            samples.append({
                "sample_id": f"holdout-{sequence:03d}",
                "display_name": f"Потік відкладеної вибірки {sequence:03d}",
                "ground_truth": int(label),
                "features": {name: float(row[name]) if pd.notna(row[name]) else None for name in FEATURES},
                "signature_context": {
                    "dst_port": int(row["dst_port"]) if pd.notna(row["dst_port"]) else -1,
                    "src_pkts": float(row["src_pkts"]) if pd.notna(row["src_pkts"]) else 0.0,
                    "conn_state": str(row["conn_state"]),
                },
            })
    return samples
