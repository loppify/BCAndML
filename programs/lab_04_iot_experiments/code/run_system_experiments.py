"""Run local API load, end-to-end timing and centralized SQLite baseline trials."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
import numpy as np
from web3 import HTTPProvider, Web3


ROOT = Path(__file__).resolve().parents[1]
LAB3_PROJECT = ROOT.parent / "lab_03_iot_ml_integration"
LAB3 = LAB3_PROJECT / "code" if (LAB3_PROJECT / "code").is_dir() else LAB3_PROJECT
sys.path.insert(0, str(LAB3))
OUT = ROOT / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://127.0.0.1:8080"
RPC_URL = "http://127.0.0.1:8545"


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype="float64"), q)) if values else 0.0


async def run_gateway_load(device_id: str, actor: str, users: int, requests_per_user: int) -> dict:
    total_requests = users * requests_per_user
    semaphore = asyncio.Semaphore(users)
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    latencies: list[float] = []
    statuses: list[int] = []
    errors: list[str] = []
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        async def request_one(index: int) -> None:
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    response = await client.post(f"{BASE_URL}/api/gateway/check",
                                                 json={"device_id": device_id, "actor": actor})
                    latencies.append((time.perf_counter() - t0) * 1000)
                    statuses.append(response.status_code)
                    if response.status_code != 200 or not response.json().get("allowed"):
                        errors.append(f"request {index}: HTTP {response.status_code}, {response.text[:160]}")
                except Exception as exc:
                    latencies.append((time.perf_counter() - t0) * 1000)
                    errors.append(f"request {index}: {type(exc).__name__}: {exc}")
        await asyncio.gather(*(request_one(i) for i in range(total_requests)))
    elapsed = time.perf_counter() - started
    return {
        "simulated_concurrent_users": users,
        "requests_per_user": requests_per_user,
        "requests_total": total_requests,
        "successful_http_200": sum(status == 200 for status in statuses),
        "failed_or_denied": len(errors),
        "elapsed_seconds": elapsed,
        "throughput_requests_per_second": total_requests / elapsed if elapsed else 0.0,
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95),
                       "p99": percentile(latencies, 99), "max": max(latencies, default=0.0)},
        "error_examples": errors[:5],
    }


def launch_demo(log_path: Path) -> subprocess.Popen:
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "scripts/run_demo.py", "--port", "8080"],
                               cwd=LAB3, stdout=log, stderr=subprocess.STDOUT,
                               env={**os.environ, "WEB3_PROVIDER_URL": RPC_URL},
                               start_new_session=True)
    process._lab4_log_handle = log  # keep the redirected stream alive until shutdown
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Demo server exited early; inspect {log_path}")
        try:
            response = httpx.get(f"{BASE_URL}/api/health", timeout=1)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return process
        except Exception:
            pass
        time.sleep(.5)
    raise TimeoutError(f"Demo API did not become ready; inspect {log_path}")


def stop_demo(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    process._lab4_log_handle.close()


def register_test_device(w3: Web3, deployment: dict, artifact_root: Path) -> tuple[str, str]:
    def abi(contract: str, source: str) -> list:
        return json.loads((artifact_root / source / f"{contract}.json").read_text(encoding="utf-8"))["abi"]
    registry = w3.eth.contract(address=deployment["contracts"]["registry"],
                               abi=abi("DeviceRegistry", "contracts/DeviceRegistry.sol"))
    access = w3.eth.contract(address=deployment["contracts"]["access_control"],
                             abi=abi("AccessControl", "contracts/AccessControl.sol"))
    owner = Web3.to_checksum_address(deployment["roles"]["owner"])
    actor = Web3.to_checksum_address(deployment["roles"]["actor"])
    salt = Web3.keccak(text=f"lab4-load-device-{uuid4()}")
    metadata_hash = Web3.keccak(text=f"lab4-load-metadata-{uuid4()}")
    receipt = w3.eth.wait_for_transaction_receipt(
        registry.functions.registerDevice(salt, metadata_hash).transact({"from": owner})
    )
    if int(receipt.status) != 1:
        raise RuntimeError("Local benchmark device registration reverted")
    device_id = Web3.to_hex(Web3.keccak(w3.codec.encode(["address", "bytes32"], [owner, salt]))).lower()
    valid_until = int(time.time()) + 86400
    grant_receipt = w3.eth.wait_for_transaction_receipt(
        access.functions.grantAccess(Web3.to_bytes(hexstr=device_id), actor, valid_until).transact({"from": owner})
    )
    if int(grant_receipt.status) != 1:
        raise RuntimeError("Local benchmark access grant reverted")
    return device_id, actor


def measure_component_breakdown(device_id: str, features: dict, repeats: int = 5) -> dict:
    from app.blockchain import BlockchainService
    from app.data_pipeline import canonical_flow_payload, canonical_json, sha256_hex
    from app.database import SQLiteRepository, utc_now
    from app.model_runtime import ModelRuntime
    from app.settings import settings

    model = ModelRuntime(settings.model_path, settings.model_card_path)
    warm_prediction = model.predict(features)
    model.explain(warm_prediction["features"])
    repository = SQLiteRepository(settings.database_path)
    blockchain = BlockchainService(settings, repository)
    device = Web3.to_bytes(hexstr=device_id)
    device_info = blockchain.device_owner(device_id)
    registry_meta = Web3.to_hex(blockchain.contracts["registry"].functions.metadataHashOf(device).call())
    repository.save_device(device_id, "Lab 4 benchmark device", device_info, registry_meta)
    samples = []
    for repeat in range(1, repeats + 1):
        flow_id = f"lab4-component-{repeat}-{uuid4()}"
        started = time.perf_counter()
        t = time.perf_counter()
        state = blockchain.device_status(device_id)
        state_read_ms = (time.perf_counter() - t) * 1000
        if state["state"] != "Active":
            raise RuntimeError("Benchmark device is not active")
        observed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        t = time.perf_counter()
        payload = canonical_flow_payload({"flow_id": flow_id, "device_id": device_id,
                                          "observed_at": observed_at, "schema_version": "ton_iot_numeric_v1",
                                          "features": features})
        digest = sha256_hex(canonical_json(payload))
        hash_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        prediction = model.predict(features)
        prediction_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        explanations = model.explain(prediction["features"])
        shap_ms = (time.perf_counter() - t) * 1000
        prediction_id = str(uuid4())
        t = time.perf_counter()
        repository.save_flow(flow_id, device_id, digest, observed_at, features)
        repository.save_prediction(prediction_id, flow_id, device_id, prediction["model_version"], digest,
                                   prediction["is_attack"], prediction["confidence_bps"], status="pending")
        sqlite_write_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        chain = blockchain.send_decision(device_id, prediction["is_attack"], prediction["confidence_bps"],
                                         prediction["model_version"], digest)
        chain_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        repository.update_prediction_chain(prediction_id, chain["tx_hash"], chain["block_number"], "confirmed")
        blockchain.refresh_event_mirror()
        mirror_ms = (time.perf_counter() - t) * 1000
        total_ms = (time.perf_counter() - started) * 1000
        samples.append({"repeat": repeat, "flow_id": flow_id, "is_attack": prediction["is_attack"],
                        "confidence_bps": prediction["confidence_bps"], "shap_factors": len(explanations),
                        "tx_hash": chain["tx_hash"], "stage_ms": {"state_read": state_read_ms,
                        "canonicalization_and_hash": hash_ms, "model_prediction": prediction_ms,
                        "shap_explanation": shap_ms, "sqlite_writes": sqlite_write_ms,
                        "oracle_transaction_and_receipt": chain_ms, "sqlite_event_mirror": mirror_ms,
                        "sum_instrumented_stages": state_read_ms + hash_ms + prediction_ms + shap_ms + sqlite_write_ms + chain_ms + mirror_ms,
                        "total": total_ms}})
    stage_names = list(samples[0]["stage_ms"])
    means = {name: float(np.mean([sample["stage_ms"][name] for sample in samples])) for name in stage_names}
    return {"repetitions": repeats, "samples": samples, "mean_stage_ms": means,
            "e2e_total_ms": [sample["stage_ms"]["total"] for sample in samples]}


def measure_centralized(features: dict, repeats: int = 5) -> dict:
    from app.model_runtime import ModelRuntime
    from app.settings import settings
    model = ModelRuntime(settings.model_path, settings.model_card_path)
    warm_prediction = model.predict(features)
    model.explain(warm_prediction["features"])
    samples = []
    with tempfile.TemporaryDirectory(prefix="lab4-central-") as temp_dir:
        db_path = Path(temp_dir) / "central.sqlite3"
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE records (flow_id TEXT PRIMARY KEY, input_json TEXT, prediction INTEGER, confidence INTEGER)")
        for repeat in range(1, repeats + 1):
            flow_id = f"central-{repeat}-{uuid4()}"
            started = time.perf_counter()
            payload = json.dumps(features, sort_keys=True, separators=(",", ":"))
            prediction = model.predict(features)
            model.explain(prediction["features"])
            with sqlite3.connect(db_path) as db:
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?)",
                           (flow_id, payload, int(prediction["is_attack"]), prediction["confidence_bps"]))
            samples.append({"repeat": repeat, "latency_ms": (time.perf_counter() - started) * 1000,
                            "flow_id": flow_id, "stored": True})
    return {"repetitions": repeats, "samples": samples,
            "mean_ms": float(np.mean([row["latency_ms"] for row in samples])),
            "p95_ms": percentile([row["latency_ms"] for row in samples], 95),
            "note": "Same model and SHAP path; one local SQLite insert; no EVM, external oracle, or decentralized audit.",
            "tamper_test": {"can_update_local_record_without_external_anchor": True}}


def main() -> None:
    log_path = OUT / "local-demo-server.log"
    process = launch_demo(log_path)
    try:
        response = httpx.get(f"{BASE_URL}/api/config", timeout=10)
        response.raise_for_status()
        config = response.json()
        deployment = json.loads((LAB3 / "deployments" / "localhost.json").read_text(encoding="utf-8"))
        w3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 15}))
        device_id, actor = register_test_device(w3, deployment, LAB3 / "build" / "hardhat-artifacts")

        flows = json.loads((LAB3 / "artifacts" / "demo_flows.json").read_text(encoding="utf-8"))
        truth = json.loads((LAB3 / "artifacts" / "demo_flow_truth.json").read_text(encoding="utf-8"))
        normal = next(flow for flow in flows if truth[str(flow["sample_id"])] == 0)
        features = normal["features"]

        inference_samples = []
        with httpx.Client(timeout=90) as client:
            warmup = client.post(f"{BASE_URL}/api/inference", json={
                "flow_id": f"lab4-api-warmup-{uuid4()}", "device_id": device_id,
                "features": features, "signature_context": normal.get("signature_context")})
            if warmup.status_code != 200:
                raise RuntimeError(f"API warm-up failed: HTTP {warmup.status_code}: {warmup.text[:500]}")
            for repeat in range(1, 6):
                request_data = {"flow_id": f"lab4-http-{repeat}-{uuid4()}", "device_id": device_id,
                                "features": features, "signature_context": normal.get("signature_context")}
                t0 = time.perf_counter()
                result = client.post(f"{BASE_URL}/api/inference", json=request_data)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if result.status_code != 200:
                    raise RuntimeError(f"Local API inference failed: HTTP {result.status_code}: {result.text[:500]}")
                body = result.json()
                inference_samples.append({"repeat": repeat, "latency_ms": elapsed_ms,
                                          "status": result.status_code, "is_attack": body["is_attack"],
                                          "tx_hash": body["tx_hash"], "confidence_bps": body["confidence_bps"]})

        component = measure_component_breakdown(device_id, features, 5)
        central = measure_centralized(features, 5)
        load_rows = [asyncio.run(run_gateway_load(device_id, actor, users, 10)) for users in (10, 50, 100)]
        sequential_gateway = asyncio.run(run_gateway_load(device_id, actor, 1, 1000))

        output = {
            "network": "Hardhat local EVM and FastAPI on one local host",
            "chain_id": 31337,
            "device_id": device_id,
            "simulated_load_scope": "POST /api/gateway/check read path, 10 requests per concurrent virtual user; inference write-path measured serially in five E2E trials.",
            "gateway_load": load_rows,
            "gateway_nfr_1000_sequential": sequential_gateway,
            "api_inference_e2e": {
                "repetitions": len(inference_samples), "samples": inference_samples,
                "mean_ms": float(np.mean([row["latency_ms"] for row in inference_samples])),
                "p95_ms": percentile([row["latency_ms"] for row in inference_samples], 95),
            },
            "component_breakdown": component,
            "centralized_baseline": central,
            "provider": {"chain_id": int(w3.eth.chain_id), "connected": w3.is_connected()},
        }
        output_path = OUT / "system_experiments.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output_path), "gateway_load": [
            {"users": row["simulated_concurrent_users"], "throughput_rps": row["throughput_requests_per_second"],
             "p95_ms": row["latency_ms"]["p95"], "errors": row["failed_or_denied"]} for row in load_rows],
            "api_inference_mean_ms": output["api_inference_e2e"]["mean_ms"],
            "central_mean_ms": central["mean_ms"]}, indent=2))
    finally:
        stop_demo(process)
        if log_path.exists():
            log_path.unlink()


if __name__ == "__main__":
    main()
