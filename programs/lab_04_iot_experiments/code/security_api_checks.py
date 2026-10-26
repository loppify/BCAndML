"""Exercise API abuse, integrity and injected-failure paths using isolated fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LAB3_PROJECT = ROOT.parent / "lab_03_iot_ml_integration"
LAB3 = LAB3_PROJECT / "code" if (LAB3_PROJECT / "code").is_dir() else LAB3_PROJECT
sys.path.insert(0, str(LAB3))
sys.path.insert(0, str(LAB3 / "tests"))
import test_api  # noqa: E402


def run_check(name, execute) -> dict:
    with tempfile.TemporaryDirectory(prefix="lab4-security-") as temp:
        client, blockchain, repository = test_api.make_client(Path(temp))
        with client:
            try:
                details = execute(client, blockchain, repository)
                passed = bool(details.pop("passed"))
                return {"check": name, "passed": passed, **details}
            except Exception as exc:
                return {"check": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}


def label_injection(client, blockchain, _repository):
    payload = test_api.inference_payload("attack-label-injection")
    payload["features"]["label"] = 1
    response = client.post("/api/inference", json=payload)
    return {"http_status": response.status_code, "chain_submissions": blockchain.calls,
            "passed": response.status_code == 422 and blockchain.calls == 0}


def non_finite_input(client, blockchain, _repository):
    payload = test_api.inference_payload("attack-infinite-feature")
    payload["features"]["src_bytes"] = float("inf")
    response = client.post("/api/inference", content=json.dumps(payload, allow_nan=True),
                           headers={"Content-Type": "application/json"})
    return {"http_status": response.status_code, "chain_submissions": blockchain.calls,
            "passed": response.status_code == 422 and blockchain.calls == 0,
            "response_excerpt": response.text[:180]}


def replay_submission(client, blockchain, _repository):
    payload = test_api.inference_payload("attack-replay-key")
    first = client.post("/api/inference", json=payload)
    second = client.post("/api/inference", json=payload)
    return {"first_status": first.status_code, "replay_status": second.status_code,
            "replay_flag": second.json().get("replayed"), "chain_submissions": blockchain.calls,
            "passed": first.status_code == second.status_code == 200 and second.json().get("replayed") is True and blockchain.calls == 1}


def payload_tampering(client, _blockchain, _repository):
    result = client.post("/api/inference", json=test_api.inference_payload("attack-payload-tamper")).json()
    stored = client.get(f"/api/integrity/{result['flow_id']}").json()["payload"]
    stored["features"]["src_pkts"] += 1
    checked = client.post(f"/api/integrity/{result['flow_id']}/check", json={"payload": stored})
    return {"http_status": checked.status_code, "valid_after_change": checked.json().get("valid"),
            "passed": checked.status_code == 200 and checked.json().get("valid") is False}


def hundred_integrity_mutations(client, _blockchain, _repository):
    result = client.post("/api/inference", json=test_api.inference_payload("attack-100-integrity-mutants")).json()
    original = client.get(f"/api/integrity/{result['flow_id']}").json()["payload"]
    rejected = 0
    for index in range(1, 101):
        changed = json.loads(json.dumps(original))
        changed["features"]["src_pkts"] += index
        response = client.post(f"/api/integrity/{result['flow_id']}/check", json={"payload": changed})
        if response.status_code == 200 and response.json().get("valid") is False:
            rejected += 1
    return {"intentional_mutations": 100, "detected_mutations": rejected,
            "detection_rate": rejected / 100, "passed": rejected == 100}


def unauthorized_gateway_actor(client, _blockchain, _repository):
    response = client.post("/api/gateway/check", json={"device_id": test_api.DEVICE_ID,
                                                       "actor": "0x0000000000000000000000000000000000000099"})
    body = response.json()
    return {"http_status": response.status_code, "allowed": body.get("allowed"),
            "reason": body.get("reason"), "passed": response.status_code == 200 and body.get("allowed") is False}


def oracle_outage(client, blockchain, repository):
    def outage(*_args, **_kwargs):
        raise ConnectionError("Injected RPC unavailable")
    blockchain.send_decision = outage
    payload = test_api.inference_payload("fault-oracle-outage")
    response = client.post("/api/inference", json=payload)
    stored = repository.prediction_for_flow(payload["flow_id"])
    return {"http_status": response.status_code, "prediction_status": stored["status"],
            "oracle_monitor": client.get("/api/oracle/status").json(),
            "passed": response.status_code == 502 and stored["status"] == "failed"}


def database_outage(client, blockchain, repository):
    def disk_failure(*_args, **_kwargs):
        raise sqlite3.OperationalError("Injected database unavailable")
    repository.save_flow = disk_failure
    payload = test_api.inference_payload("fault-database-outage")
    response = client.post("/api/inference", json=payload)
    return {"http_status": response.status_code, "chain_submissions": blockchain.calls,
            "client_message": response.json().get("detail", "")[:180],
            "passed": response.status_code == 502 and blockchain.calls == 0}


def reverted_transaction(client, blockchain, repository):
    def revert(*_args, **_kwargs):
        raise ValueError("execution reverted: Unauthorized")
    blockchain.send_decision = revert
    payload = test_api.inference_payload("fault-transaction-revert")
    response = client.post("/api/inference", json=payload)
    stored = repository.prediction_for_flow(payload["flow_id"])
    return {"http_status": response.status_code, "prediction_status": stored["status"],
            "error_reported": "reverted" in response.json().get("detail", "").lower(),
            "passed": response.status_code == 422 and stored["status"] == "failed" and
                     "reverted" in response.json().get("detail", "").lower()}


def main() -> None:
    checks = [
        run_check("Підміна мітки атаки у payload", label_injection),
        run_check("Нескінченне значення ознаки", non_finite_input),
        run_check("Повторне відправлення flow ID", replay_submission),
        run_check("Підміна збережених ознак", payload_tampering),
        run_check("100 контрольних змін для SHA-256 integrity", hundred_integrity_mutations),
        run_check("Команда від неавторизованого gateway actor", unauthorized_gateway_actor),
        run_check("Недоступність oracle/RPC", oracle_outage),
        run_check("Недоступність SQLite", database_outage),
        run_check("Відхилення транзакції контрактом", reverted_transaction),
    ]
    output = {
        "test_method": "Isolated FastAPI TestClient with injected service/database faults; contract-level role/replay checks are in security_contract_checks.json.",
        "attempted_checks": len(checks),
        "passed_checks": sum(row["passed"] for row in checks),
        "checks": checks,
        "ipfs": {"used_by_system": False, "failure_test": "not applicable; artifacts use local filesystem and SQLite"},
    }
    output_path = ROOT / "artifacts" / "security_api_checks.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "passed": output["passed_checks"], "total": output["attempted_checks"]}, indent=2))
    if output["passed_checks"] != output["attempted_checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
