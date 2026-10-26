"""Application settings shared by training, API and local EVM integration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


CODE_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = CODE_ROOT.parent
load_dotenv(CODE_ROOT / ".env")


def _path_from_env(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else CODE_ROOT / value


@dataclass(frozen=True)
class Settings:
    code_root: Path = CODE_ROOT
    work_root: Path = WORK_ROOT
    dataset_path: Path = _path_from_env("DATASET_PATH", "data/raw/ton_iot_network.csv")
    model_path: Path = _path_from_env("MODEL_PATH", "models/random_forest_v2.joblib")
    model_card_path: Path = _path_from_env("MODEL_CARD_PATH", "models/model_card.json")
    deployment_path: Path = _path_from_env("DEPLOYMENT_PATH", "deployments/localhost.json")
    database_path: Path = _path_from_env("DATABASE_PATH", "artifacts/iot_ids.sqlite3")
    demo_flows_path: Path = _path_from_env("DEMO_FLOWS_PATH", "artifacts/demo_flows.json")
    rpc_url: str = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:8545")
    oracle_private_key: str = os.getenv("ORACLE_PRIVATE_KEY", "").strip()
    oracle_address: str = os.getenv("ORACLE_ADDRESS", "").strip()
    model_version: int = int(os.getenv("MODEL_VERSION", "2"))
    confidence_threshold_bps: int = int(os.getenv("CONFIDENCE_THRESHOLD_BPS", "5000"))
    chain_id: int = int(os.getenv("CHAIN_ID", "31337"))
    explorer_base_url: str = os.getenv("EXPLORER_BASE_URL", "").strip().rstrip("/")
    database_poll_seconds: float = float(os.getenv("DATABASE_POLL_SECONDS", "3"))


settings = Settings()
