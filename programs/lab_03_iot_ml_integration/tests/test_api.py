from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
import pandas as pd

from app.api import ServiceContainer, create_app
from app.data_pipeline import FEATURES
from app.database import SQLiteRepository


DEVICE_ID = "0x" + "11" * 32
OWNER = "0x0000000000000000000000000000000000000002"
TX_HASH = "0x" + "ab" * 32


class FakeModel:
    version = 2
    model_hash = "0x" + "22" * 32

    def public_card(self):
        return {
            "model_name": "Test Random Forest",
            "model_version": 2,
            "artifact_sha256": self.model_hash,
            "held_out_test_metrics": {"f1_attack": 0.9, "precision_attack": 0.9, "recall_attack": 0.9, "pr_auc": 0.9},
            "group_cv_f1_mean": 0.88,
            "group_cv_f1_sd": 0.03,
        }

    def predict(self, features):
        return {"is_attack": True, "confidence": 0.91, "confidence_bps": 9100,
                "model_version": 2, "artifact_hash": self.model_hash,
                "features": pd.DataFrame([features], columns=FEATURES)}

    def explain(self, frame):
        return [{"feature": "src_pkts", "value": 12.0, "contribution": 0.31,
                 "direction": "підвищує оцінку атаки", "method": "SHAP TreeExplainer"}]


class FakeBlockchain:
    config = type("Config", (), {"explorer_base_url": ""})()

    def __init__(self):
        self.calls = 0
        self.events = []

    def network_status(self):
        return {"connected": True, "chain_id": 31337, "expected_chain_id": 31337, "block_number": 10}

    def public_config(self):
        return {"chain_id": 31337, "expected_chain_id": 31337,
                "roles": {"admin": OWNER, "owner": OWNER, "gateway": OWNER, "oracle": OWNER, "auditor": OWNER, "actor": OWNER},
                "contracts": {}, "start_block": 1, "model_version": 2,
                "model_hash": FakeModel.model_hash, "registered_model_hash": FakeModel.model_hash,
                "confidence_threshold_bps": 5000, "explorer_base_url": ""}

    def device_status(self, device_id):
        return {"device_id": device_id, "state": "Active" if device_id == DEVICE_ID else "Unregistered", "status_code": 1}

    def device_owner(self, device_id):
        return OWNER

    class Registry:
        class Functions:
            @staticmethod
            def metadataHashOf(_device_id):
                class Call:
                    @staticmethod
                    def call(): return bytes.fromhex("33" * 32)
                return Call()
        functions = Functions()

    class Quarantine:
        class Functions:
            @staticmethod
            def paused():
                class Call:
                    @staticmethod
                    def call(): return False
                return Call()
        functions = Functions()

    contracts = {"registry": Registry(), "quarantine": Quarantine()}

    def send_decision(self, device_id, is_attack, confidence, version, input_hash):
        self.calls += 1
        event = {"event_name": "DecisionRecorded", "tx_hash": TX_HASH, "log_index": self.calls,
                 "block_number": 11 + self.calls, "device_id": device_id,
                 "model_version": version,
                 "args": {"deviceId": device_id, "attack": is_attack, "confidence": confidence,
                          "modelVersion": version, "inputHash": input_hash}}
        self.events.append(event)
        return {"tx_hash": TX_HASH, "block_number": 11 + self.calls, "replayed": False}

    def find_decision(self, device_id, input_hash):
        for event in self.events:
            args = event["args"]
            if event["device_id"] == device_id and args["inputHash"].lower() == input_hash.lower():
                return {"tx_hash": event["tx_hash"], "block_number": event["block_number"],
                        "input_hash": args["inputHash"]}
        return None

    def refresh_event_mirror(self):
        return list(self.events)

    def audit_history(self, limit=100):
        return list(reversed(self.events[-limit:]))

    def registered_devices(self):
        return [{"device_id": DEVICE_ID, "owner_address": OWNER, "metadata_hash": "0x" + "33" * 32,
                 "local_name": "Test sensor", "state": "Active", "status_code": 1}]

    def prepare_owner_transaction(self, action, payload, sender):
        return {"to": "0x" + "44" * 20, "data": "0x1234", "chain_id": 31337,
                "action": action, "extra": {"sender": sender, **payload}}

    def confirm_wallet_transaction(self, tx_hash, action, extra):
        return {"tx_hash": tx_hash, "block_number": 12, "status": "confirmed", "action": action, **extra}

    def gateway_can_interact(self, device_id, actor):
        return device_id == DEVICE_ID and actor == OWNER


def make_client(tmp_path: Path) -> tuple[TestClient, FakeBlockchain, SQLiteRepository]:
    repository = SQLiteRepository(tmp_path / "test.sqlite3")
    repository.save_device(DEVICE_ID, "Test sensor", OWNER, "0x" + "33" * 32)
    repository.save_model(2, "model.joblib", FakeModel.model_hash, "ton_iot_numeric_v1", 5000, {"f1": 0.9})
    blockchain = FakeBlockchain()
    services = ServiceContainer(model=FakeModel(), blockchain=blockchain, repository=repository,
                                demo_flows=[{"sample_id": "holdout-001", "display_name": "Holdout flow",
                                             "features": {name: 1.0 for name in FEATURES},
                                             "signature_context": {"dst_port": 443, "src_pkts": 4, "conn_state": "SF"},
                                             "ground_truth": 0}])
    return TestClient(create_app(services=services)), blockchain, repository


def inference_payload(flow_id="flow-001"):
    return {"flow_id": flow_id, "device_id": DEVICE_ID, "features": {name: 1.0 for name in FEATURES},
            "signature_context": {"dst_port": 443, "src_pkts": 4, "conn_state": "SF"}}


def test_health_and_chain_status(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["chain"]["chain_id"] == 31337


def test_public_chain_configuration(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["model_version"] == 2


def test_openapi_schema_is_available(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/inference" in response.json()["paths"]


def test_model_card_and_comparison_endpoint(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["primary"]["model_name"] == "Test Random Forest"


def test_demo_samples_do_not_expose_ground_truth(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/demo-flows")
    assert response.status_code == 200
    assert "ground_truth" not in response.json()[0]
    assert "label" not in response.json()[0]["features"]


def test_devices_are_read_from_registry_service(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/devices")
    assert response.status_code == 200
    assert response.json()[0]["device_id"] == DEVICE_ID


def test_prepare_wallet_transaction_returns_calldata(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.post("/api/transactions/prepare", json={"action": "register_device", "sender": OWNER, "payload": {"local_name": "Room sensor"}})
    assert response.status_code == 200
    assert response.json()["data"].startswith("0x")


def test_confirm_wallet_transaction_returns_receipt_status(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.post("/api/transactions/confirm", json={"action": "grant_access", "tx_hash": TX_HASH, "extra": {"device_id": DEVICE_ID}})
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_inference_runs_model_and_records_realistic_oracle_receipt(tmp_path):
    client, blockchain, _ = make_client(tmp_path)
    response = client.post("/api/inference", json=inference_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["is_attack"] is True
    assert body["confidence_bps"] == 9100
    assert body["input_hash"].startswith("0x")
    assert body["tx_hash"] == TX_HASH
    assert body["explanations"][0]["feature"] == "src_pkts"
    assert blockchain.calls == 1


def test_inference_idempotency_does_not_submit_twice(tmp_path):
    client, blockchain, _ = make_client(tmp_path)
    first = client.post("/api/inference", json=inference_payload("retry-key"))
    second = client.post("/api/inference", json=inference_payload("retry-key"))
    assert first.status_code == second.status_code == 200
    assert blockchain.calls == 1
    assert second.json()["replayed"] is True


def test_inference_rejects_unregistered_device(tmp_path):
    client, blockchain, _ = make_client(tmp_path)
    payload = inference_payload("unknown-device")
    payload["device_id"] = "0x" + "99" * 32
    assert client.post("/api/inference", json=payload).status_code == 422
    assert blockchain.calls == 0


def test_inference_rejects_extra_label_and_ip_fields(tmp_path):
    client, _, _ = make_client(tmp_path)
    payload = inference_payload("no-leak")
    payload["features"]["label"] = 1
    response = client.post("/api/inference", json=payload)
    assert response.status_code == 422


def test_audit_history_returns_chain_events(tmp_path):
    client, _, _ = make_client(tmp_path)
    client.post("/api/inference", json=inference_payload("audit-flow"))
    response = client.get("/api/audit")
    assert response.status_code == 200
    assert response.json()["events"][0]["event_name"] == "DecisionRecorded"


def test_gateway_allows_authorized_active_actor(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.post("/api/gateway/check", json={"device_id": DEVICE_ID, "actor": OWNER})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_integrity_accepts_original_payload_and_rejects_tampering(tmp_path):
    client, _, _ = make_client(tmp_path)
    result = client.post("/api/inference", json=inference_payload("integrity-flow")).json()
    stored = client.get(f"/api/integrity/{result['flow_id']}").json()
    valid = client.post(f"/api/integrity/{result['flow_id']}/check", json={"payload": stored["payload"]})
    assert valid.status_code == 200 and valid.json()["valid"] is True
    # Browser JSON.stringify serializes integral numbers without a trailing .0.
    browser_payload = stored["payload"]
    browser_payload["features"] = {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in browser_payload["features"].items()
    }
    browser_roundtrip = client.post(f"/api/integrity/{result['flow_id']}/check", json={"payload": browser_payload})
    assert browser_roundtrip.status_code == 200 and browser_roundtrip.json()["valid"] is True
    changed = stored["payload"]
    changed["features"]["src_pkts"] = 999
    invalid = client.post(f"/api/integrity/{result['flow_id']}/check", json={"payload": changed})
    assert invalid.status_code == 200 and invalid.json()["valid"] is False
