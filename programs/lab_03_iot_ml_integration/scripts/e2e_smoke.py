"""Run the full HTTP-to-Hardhat scenario and save verified transaction evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import httpx
from web3 import HTTPProvider, Web3


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8080"
RPC_URL = "http://127.0.0.1:8545"


def ready() -> bool:
    try:
        request = Request(BASE_URL + "/api/health")
        with urlopen(request, timeout=1) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def submit_wallet_action(client: httpx.Client, w3: Web3, sender: str, action: str, payload: dict):
    prepared = client.post("/api/transactions/prepare", json={"action": action, "sender": sender, "payload": payload})
    prepared.raise_for_status()
    tx = prepared.json()
    tx_hash = w3.eth.send_transaction({"from": sender, "to": tx["to"], "data": tx["data"]})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
    if int(receipt["status"]) != 1:
        raise RuntimeError(f"{action} transaction reverted: {Web3.to_hex(tx_hash)}")
    confirmed = client.post("/api/transactions/confirm", json={
        "action": action, "tx_hash": Web3.to_hex(tx_hash), "extra": tx["extra"],
    })
    confirmed.raise_for_status()
    return confirmed.json()


def main() -> None:
    log_path = ROOT / "artifacts" / "e2e-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable, "scripts/run_demo.py"], cwd=ROOT, env=env,
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        success = False
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and server.poll() is None:
                if ready():
                    break
                time.sleep(0.5)
            if not ready():
                raise RuntimeError(f"Demo server failed to start. Inspect {log_path}.")

            w3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 10}))
            if not w3.is_connected():
                raise RuntimeError("Hardhat JSON-RPC is not reachable.")
            config = httpx.get(BASE_URL + "/api/config", timeout=15).json()
            roles = config["roles"]
            owner = Web3.to_checksum_address(roles["owner"])
            actor = Web3.to_checksum_address(roles["actor"])
            auditor = Web3.to_checksum_address(roles["auditor"])
            client = httpx.Client(base_url=BASE_URL, timeout=120)

            registered = []
            for label in ("Virtual normal sensor", "Virtual attack sensor", "Virtual audit sensor"):
                registered.append(submit_wallet_action(client, w3, owner, "register_device", {"local_name": label}))
            device_ids = [record["device_id"] for record in registered]
            grants = [
                submit_wallet_action(client, w3, owner, "grant_access", {
                    "device_id": device_id, "actor": actor,
                    "valid_until": int(time.time()) + 86_400,
                })
                for device_id in device_ids[:2]
            ]

            with (ROOT / "artifacts" / "demo_flow_truth.json").open(encoding="utf-8") as file:
                truths = json.load(file)
            with (ROOT / "artifacts" / "demo_flows.json").open(encoding="utf-8") as file:
                samples = json.load(file)
            normal_sample = next(sample for sample in samples if truths[sample["sample_id"]] == 0)
            attack_sample = next(sample for sample in samples if truths[sample["sample_id"]] == 1)

            normal_started = time.perf_counter()
            normal = client.post("/api/inference", json={
                "flow_id": "e2e-normal-001", "device_id": device_ids[0],
                "features": normal_sample["features"], "signature_context": normal_sample["signature_context"],
            })
            if not normal.is_success:
                raise RuntimeError(f"Normal-flow inference failed: {normal.status_code} {normal.text}")
            normal_elapsed = time.perf_counter() - normal_started
            attack_started = time.perf_counter()
            attack = client.post("/api/inference", json={
                "flow_id": "e2e-attack-001", "device_id": device_ids[1],
                "features": attack_sample["features"], "signature_context": attack_sample["signature_context"],
            })
            if not attack.is_success:
                raise RuntimeError(f"Attack-flow inference failed: {attack.status_code} {attack.text}")
            attack_elapsed = time.perf_counter() - attack_started
            normal_result, attack_result = normal.json(), attack.json()
            if normal_result["is_attack"] or not attack_result["is_attack"]:
                raise AssertionError("Selected held-out examples did not exercise the expected model decision branches.")

            active_access = client.post("/api/gateway/check", json={"device_id": device_ids[0], "actor": actor})
            quarantine_access = client.post("/api/gateway/check", json={"device_id": device_ids[1], "actor": actor})
            active_access.raise_for_status()
            quarantine_access.raise_for_status()
            if not active_access.json()["allowed"] or quarantine_access.json()["allowed"]:
                raise AssertionError(
                    "Gateway policy did not allow active access and deny quarantined access: "
                    f"active={active_access.json()} quarantined={quarantine_access.json()} "
                    f"normal={normal_result} attack={attack_result}"
                )

            original = client.get(f"/api/integrity/{attack_result['flow_id']}")
            original.raise_for_status()
            original_payload = original.json()["payload"]
            valid = client.post(f"/api/integrity/{attack_result['flow_id']}/check", json={"payload": original_payload})
            tampered_payload = json.loads(json.dumps(original_payload))
            tampered_payload["features"]["src_pkts"] = float(tampered_payload["features"]["src_pkts"] or 0) + 1.0
            tampered = client.post(f"/api/integrity/{attack_result['flow_id']}/check", json={"payload": tampered_payload})
            valid.raise_for_status()
            tampered.raise_for_status()
            if not valid.json()["valid"] or tampered.json()["valid"]:
                raise AssertionError("The interface integrity check did not distinguish original and changed payloads.")

            bad_schema = dict(attack_sample["features"])
            bad_schema["label"] = 1
            denied_input = client.post("/api/inference", json={
                "flow_id": "e2e-negative-schema", "device_id": device_ids[2], "features": bad_schema,
            })
            if denied_input.status_code not in (422, 400):
                raise AssertionError(f"The API accepted a label-leaking feature schema: {denied_input.status_code}")

            # Confirm role enforcement at the contract, not just a disabled UI control.
            unprivileged = client.post("/api/transactions/prepare", json={
                "action": "grant_access", "sender": auditor,
                "payload": {"device_id": device_ids[2], "actor": actor, "valid_until": int(time.time()) + 3600},
            })
            unprivileged.raise_for_status()
            unauthorized_tx = unprivileged.json()
            unauthorized_rejected = False
            try:
                w3.eth.estimate_gas({"from": auditor, "to": unauthorized_tx["to"], "data": unauthorized_tx["data"]})
            except Exception:
                unauthorized_rejected = True
            if not unauthorized_rejected:
                raise AssertionError("The AccessControl contract did not reject the auditor's unauthorized grant.")

            audit = client.get("/api/audit?limit=100")
            audit.raise_for_status()
            event_names = [event["event_name"] for event in audit.json()["events"]]
            if "DecisionRecorded" not in event_names or "DeviceQuarantined" not in event_names:
                raise AssertionError("On-chain audit history is missing the expected decision/quarantine events.")

            browser_capture = subprocess.run(["node", "scripts/capture-ui.cjs"], cwd=ROOT, env=env,
                                              capture_output=True, text=True)
            if browser_capture.returncode:
                raise RuntimeError(f"Browser E2E failed: {browser_capture.stderr}\n{browser_capture.stdout}")
            browser_evidence = json.loads(browser_capture.stdout)

            evidence = {
                "chain_id": w3.eth.chain_id,
                "model_version": config["model_version"],
                "model_hash": config["model_hash"],
                "devices": [{"device_id": item["device_id"], "tx_hash": item["tx_hash"]} for item in registered],
                "access_grants": [{"device_id": item["device_id"], "tx_hash": item["tx_hash"]} for item in grants],
                "normal_decision": {key: normal_result[key] for key in ("result", "confidence_bps", "input_hash", "tx_hash", "block_number")},
                "attack_decision": {key: attack_result[key] for key in ("result", "confidence_bps", "input_hash", "tx_hash", "block_number")},
                "inference_wall_time_seconds": {"normal": normal_elapsed, "attack": attack_elapsed},
                "gateway_active_device": active_access.json(),
                "gateway_quarantined_device": quarantine_access.json(),
                "integrity_original_valid": valid.json()["valid"],
                "integrity_changed_invalid": not tampered.json()["valid"],
                "negative_extra_label_http_status": denied_input.status_code,
                "negative_unauthorized_grant_rejected_by_contract": unauthorized_rejected,
                "audit_event_names": event_names,
                "browser_screenshots": browser_evidence["screenshots"],
                "browser_transaction_hashes": browser_evidence["browser_transaction_hashes"],
                "browser_wallet_rpc_transaction_tested": browser_evidence["browser_transactions_used_hardhat_rpc"],
            }
            output = ROOT / "artifacts" / "e2e-scenario.json"
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            success = True
            client.close()
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
            if success:
                for temporary in (
                    log_path,
                    ROOT / "artifacts" / "hardhat-node.log",
                    ROOT / "artifacts" / "iot_ids.sqlite3",
                    ROOT / "artifacts" / "iot_ids.sqlite3-wal",
                    ROOT / "artifacts" / "iot_ids.sqlite3-shm",
                    ROOT / "deployments" / "localhost.json",
                ):
                    temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
