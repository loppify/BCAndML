"""FastAPI backend and browser routes for the IoT IDS demonstration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from web3 import Web3

from app.blockchain import BlockchainService
from app.data_pipeline import FEATURES, canonical_flow_payload, canonical_json, sha256_hex, signature_prediction
from app.database import SQLiteRepository, utc_now
from app.model_runtime import ModelRuntime
from app.settings import Settings, settings


LOGGER = logging.getLogger("iot_ids.api")


@dataclass
class ServiceContainer:
    model: Any
    blockchain: Any
    repository: Any
    demo_flows: list[dict[str, Any]] = field(default_factory=list)
    oracle_monitor: dict[str, Any] = field(default_factory=lambda: {
        "status": "ready", "processed": 0, "last_success": None, "last_error": None,
    })


def build_services(config: Settings = settings) -> ServiceContainer:
    model = ModelRuntime(config.model_path, config.model_card_path)
    repository = SQLiteRepository(config.database_path)
    blockchain = BlockchainService(config, repository)
    registered_hash = blockchain.contracts["quarantine"].functions.modelHash(model.version).call()
    if Web3.to_hex(registered_hash).lower() != model.model_hash.lower():
        raise RuntimeError("Registered on-chain model hash differs from the loaded model artifact.")
    repository.save_model(
        model.version,
        str(model.model_path.relative_to(config.code_root)),
        model.model_hash,
        "ton_iot_numeric_v1",
        config.confidence_threshold_bps,
        model.card["held_out_test_metrics"],
    )
    if config.demo_flows_path.is_file():
        demo_flows = json.loads(config.demo_flows_path.read_text(encoding="utf-8"))
    else:
        demo_flows = []
    return ServiceContainer(model=model, blockchain=blockchain, repository=repository, demo_flows=demo_flows)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferenceRequest(StrictModel):
    flow_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    features: dict[str, float | None]
    signature_context: dict[str, Any] | None = None
    observed_at: str | None = None


class IntegrityRequest(StrictModel):
    payload: dict[str, Any]


class PrepareRequest(StrictModel):
    action: str
    sender: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmRequest(StrictModel):
    action: str
    tx_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    extra: dict[str, Any] = Field(default_factory=dict)


def create_application(services: ServiceContainer | None = None, config: Settings = settings) -> FastAPI:
    container = services or build_services(config)
    app = FastAPI(
        title="IoT IDS ML Oracle API",
        version="3.0.0",
        description="Grouped-evaluation Random Forest inference, model provenance and EVM audit API.",
    )
    app.state.services = container
    app.state.settings = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        status = container.blockchain.network_status()
        return {
            "status": "ok" if status["connected"] else "offline",
            "chain": status,
            "model_version": container.model.version,
            "model_hash": container.model.model_hash,
            "oracle": dict(container.oracle_monitor),
        }

    @app.get("/api/config")
    def public_config() -> dict[str, Any]:
        try:
            return container.blockchain.public_config()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Cannot read contract configuration: {exc}") from exc

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        comparison_path = config.code_root / "artifacts" / "model_comparison.csv"
        comparison = []
        if comparison_path.is_file():
            import pandas as pd
            comparison = pd.read_csv(comparison_path).to_dict(orient="records")
        return {
            "primary": container.model.public_card(),
            "comparison": comparison,
            "on_chain_hash": container.blockchain.public_config()["registered_model_hash"],
        }

    @app.get("/api/demo-flows")
    def demo_flows() -> list[dict[str, Any]]:
        # Ground-truth labels are deliberately withheld from the inference screen and request schema.
        return [{key: flow[key] for key in ("sample_id", "display_name", "features", "signature_context")}
                for flow in container.demo_flows]

    @app.get("/api/devices")
    def devices() -> list[dict[str, Any]]:
        try:
            devices_on_chain = container.blockchain.registered_devices()
            container.blockchain.refresh_event_mirror()
            return devices_on_chain
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not load device registry: {exc}") from exc

    @app.post("/api/transactions/prepare")
    def prepare_transaction(request: PrepareRequest) -> dict[str, Any]:
        try:
            return container.blockchain.prepare_owner_transaction(request.action, request.payload, request.sender)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not prepare transaction: {exc}") from exc

    @app.post("/api/transactions/confirm")
    def confirm_transaction(request: ConfirmRequest) -> dict[str, Any]:
        try:
            return container.blockchain.confirm_wallet_transaction(request.tx_hash, request.action, request.extra)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Transaction confirmation failed: {exc}") from exc

    @app.post("/api/gateway/check")
    def gateway_check(payload: dict[str, str]) -> dict[str, Any]:
        device_id = payload.get("device_id", "")
        actor = payload.get("actor", "")
        try:
            state = container.blockchain.device_status(device_id)
            allowed = container.blockchain.gateway_can_interact(device_id, actor)
            paused = bool(container.blockchain.contracts["quarantine"].functions.paused().call())
            decision = allowed and state["state"] == "Active" and not paused
            reason = "Дозвіл чинний, пристрій активний" if decision else (
                "Система на паузі" if paused else
                "Пристрій у карантині" if state["state"] == "Quarantined" else
                "Немає чинного дозволу шлюзу"
            )
            return {"allowed": decision, "reason": reason, "device_status": state["state"], "paused": paused}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Gateway check failed: {exc}") from exc

    @app.post("/api/inference")
    def infer(request: InferenceRequest) -> dict[str, Any]:
        try:
            if set(request.features) != set(FEATURES):
                missing = sorted(set(FEATURES) - set(request.features))
                extra = sorted(set(request.features) - set(FEATURES))
                raise ValueError(f"Схема ознак не відповідає моделі. Відсутні: {missing}; зайві: {extra}.")
            status = container.blockchain.device_status(request.device_id)
            if status["state"] == "Unregistered":
                raise ValueError("Спочатку зареєструйте пристрій у реєстрі.")
            existing = container.repository.prediction_for_flow(request.flow_id)
            if request.observed_at:
                observed_at = request.observed_at
            elif existing:
                stored_payload = container.repository.prediction_payload(request.flow_id)
                observed_at = stored_payload[0]["observed_at"] if stored_payload else utc_now()
            else:
                observed_at = utc_now()
            # Construct a single canonical payload. Labels, type and IPs cannot enter this schema.
            clean_features = {name: request.features[name] for name in FEATURES}
            payload = canonical_flow_payload({
                "flow_id": request.flow_id,
                "device_id": request.device_id.lower(),
                "observed_at": observed_at,
                "schema_version": "ton_iot_numeric_v1",
                "features": clean_features,
            })
            input_hash = sha256_hex(canonical_json(payload))
            prediction = container.model.predict(clean_features)
            explanation = container.model.explain(prediction["features"])
            context = request.signature_context or {
                "dst_port": clean_features["dst_port"],
                "src_pkts": clean_features["src_pkts"],
                "conn_state": "",
            }
            signature_result = bool(signature_prediction(
                context.get("dst_port", -1), context.get("src_pkts", 0), str(context.get("conn_state", ""))
            ))

            metadata = container.repository.device(request.device_id)
            if metadata is None:
                owner = container.blockchain.device_owner(request.device_id)
                metadata_hash = container.blockchain.contracts["registry"].functions.metadataHashOf(
                    Web3.to_bytes(hexstr=request.device_id)
                ).call()
                container.repository.save_device(
                    request.device_id, "Virtual IoT device", owner, Web3.to_hex(metadata_hash)
                )
            if existing:
                if existing["input_hash"].lower() != input_hash.lower():
                    raise ValueError("flow_id was already used with a different canonical input payload.")
                if existing["status"] == "confirmed":
                    return _prediction_response(container, existing, replayed=True)
                prediction_id = existing["prediction_id"]
                container.repository.update_prediction_status(prediction_id, "pending")
            else:
                container.repository.save_flow(
                    request.flow_id, request.device_id, input_hash, observed_at, clean_features
                )
                prediction_id = str(uuid4())
                container.repository.save_prediction(
                    prediction_id, request.flow_id, request.device_id, prediction["model_version"],
                    input_hash, prediction["is_attack"], prediction["confidence_bps"], status="pending",
                )
            try:
                chain_result = container.blockchain.send_decision(
                    request.device_id, prediction["is_attack"], prediction["confidence_bps"],
                    prediction["model_version"], input_hash,
                )
                container.repository.update_prediction_chain(
                    prediction_id, chain_result["tx_hash"], chain_result["block_number"], "confirmed"
                )
                container.oracle_monitor.update({
                    "status": "ready", "last_success": utc_now(), "last_error": None,
                    "processed": int(container.oracle_monitor.get("processed", 0)) + 1,
                })
            except Exception as exc:
                container.repository.update_prediction_status(prediction_id, "failed")
                container.oracle_monitor.update({"status": "error", "last_error": str(exc)[:300]})
                raise
            container.blockchain.refresh_event_mirror()
            stored = container.repository.prediction(prediction_id)
            response = _prediction_response(container, stored, replayed=bool(chain_result.get("replayed")))
            response.update({
                "probability_attack": prediction["confidence"],
                "signature_rule_attack": signature_result,
                "explanations": explanation,
                "device_status": container.blockchain.device_status(request.device_id)["state"],
                "feature_hash": input_hash,
            })
            return response
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            LOGGER.exception("Model/oracle integration failed")
            raise HTTPException(status_code=502, detail=f"Inference or oracle submission failed: {exc}") from exc

    @app.get("/api/predictions")
    def predictions(limit: int = 100) -> list[dict[str, Any]]:
        return container.repository.predictions(max(1, min(limit, 500)))

    @app.get("/api/audit")
    def audit(limit: int = 100) -> dict[str, Any]:
        try:
            events = container.blockchain.audit_history(max(1, min(limit, 500)))
            container.repository.refresh_events(events)
            return {"events": events, "source": "direct contract event logs", "mirror_count": container.repository.event_mirror_count()}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not read on-chain audit events: {exc}") from exc

    @app.get("/api/integrity/{flow_id}")
    def integrity_payload(flow_id: str) -> dict[str, Any]:
        stored = container.repository.prediction_payload(flow_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Flow not found in the local off-chain repository.")
        payload, local_hash = stored
        prediction = container.repository.prediction_for_flow(flow_id)
        chain_decision = container.blockchain.find_decision(prediction["device_id"], local_hash)
        if chain_decision is None:
            raise HTTPException(status_code=409, detail="No matching DecisionRecorded event was found in the chain.")
        return {"payload": payload, "expected_hash": local_hash, "on_chain_hash": chain_decision["input_hash"],
                "tx_hash": chain_decision["tx_hash"], "method": "SHA-256 canonical JSON matched to DecisionRecorded.inputHash"}

    @app.post("/api/integrity/{flow_id}/check")
    def integrity_check(flow_id: str, request: IntegrityRequest) -> dict[str, Any]:
        stored = container.repository.prediction_payload(flow_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Flow not found in the local off-chain repository.")
        _, local_hash = stored
        prediction = container.repository.prediction_for_flow(flow_id)
        chain_decision = container.blockchain.find_decision(prediction["device_id"], local_hash)
        if chain_decision is None:
            raise HTTPException(status_code=409, detail="No matching decision hash is available on-chain.")
        expected_hash = chain_decision["input_hash"]
        try:
            normalized_payload = canonical_flow_payload(request.payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        calculated = sha256_hex(canonical_json(normalized_payload))
        return {"flow_id": flow_id, "valid": calculated.lower() == expected_hash.lower(),
                "expected_hash": expected_hash, "calculated_hash": calculated}

    @app.get("/api/oracle/status")
    def oracle_status() -> dict[str, Any]:
        return dict(container.oracle_monitor)

    static_dir = config.code_root / "app" / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


def _prediction_response(container: ServiceContainer, record: dict[str, Any] | None, replayed: bool) -> dict[str, Any]:
    if not record:
        raise HTTPException(status_code=404, detail="Prediction record not found.")
    card = container.model.public_card()
    tx_hash = record.get("tx_hash")
    explorer = settings.explorer_base_url + "/tx/" + tx_hash if settings.explorer_base_url and tx_hash else None
    return {
        "prediction_id": record["prediction_id"],
        "flow_id": record["flow_id"],
        "device_id": record["device_id"],
        "result": "Атака" if int(record["is_attack"]) else "Нормальний трафік",
        "is_attack": bool(record["is_attack"]),
        "confidence_bps": int(record["confidence_bps"]),
        "confidence": int(record["confidence_bps"]) / 10000,
        "model_version": int(record["model_version"]),
        "model_name": card["model_name"],
        "input_hash": record["input_hash"],
        "tx_hash": tx_hash,
        "block_number": record.get("block_number"),
        "transaction_url": explorer,
        "status": record["status"],
        "replayed": replayed,
    }


def create_app(services: ServiceContainer | None = None, config: Settings = settings) -> FastAPI:
    return create_application(services=services, config=config)


class LazyApplication:
    """Create the server only when ASGI starts, so tests can inject fake services."""
    def __init__(self):
        self._application: FastAPI | None = None

    async def __call__(self, scope, receive, send):
        if self._application is None:
            self._application = create_app()
        await self._application(scope, receive, send)


app = LazyApplication()
