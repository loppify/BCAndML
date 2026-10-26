"""Measure five Sepolia recordDecision receipts using the existing Lab 2 proxy.

The script expects SEPOLIA_RPC_URL and DEPLOYER_PRIVATE_KEY in environment or
in a local, untracked .env file supplied with --env-file. It never prints keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid

from dotenv import load_dotenv
from eth_account import Account
from web3 import HTTPProvider, Web3


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
LAB2_PROJECT = ROOT.parent / "lab_02_iot_quarantine"
LAB3_PROJECT = ROOT.parent / "lab_03_iot_ml_integration"
LAB2 = LAB2_PROJECT / "code" if (LAB2_PROJECT / "code").is_dir() else LAB2_PROJECT
LAB3 = LAB3_PROJECT / "code" if (LAB3_PROJECT / "code").is_dir() else LAB3_PROJECT
if not LAB2.is_dir():
    LAB2 = REPO / "report" / "lab_02_iot_quarantine" / "code"
if not LAB3.is_dir():
    LAB3 = REPO / "report" / "lab_03_iot_ml_integration" / "code"
DEPLOYMENT = LAB2 / "deployments" / "sepolia.json"
ABI_PATH = LAB3 / "build" / "hardhat-artifacts" / "contracts" / "DeviceQuarantine.sol" / "DeviceQuarantine.json"
MODEL_PATH = LAB3 / "models" / "random_forest_v2.joblib"


def send_and_measure(w3: Web3, contract, account, device_id: bytes, model_version: int, trial: int) -> dict:
    input_hash = hashlib.sha256(f"lab4-sepolia-{trial}-{uuid.uuid4()}".encode()).digest()
    function = contract.functions.recordDecision(device_id, False, 0, model_version, input_hash)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas = function.estimate_gas({"from": account.address})
    gas_price = w3.eth.gas_price
    transaction = function.build_transaction({
        "from": account.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gas": int(gas * 1.2),
        "gasPrice": gas_price,
    })
    signed = account.sign_transaction(transaction)
    started = time.perf_counter()
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=360, poll_latency=1)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if int(receipt.status) != 1:
        raise RuntimeError(f"Sepolia transaction {tx_hash.hex()} reverted")
    return {
        "repeat": trial,
        "tx_hash": Web3.to_hex(receipt.transactionHash),
        "block_number": int(receipt.blockNumber),
        "status": int(receipt.status),
        "gas_used": int(receipt.gasUsed),
        "effective_gas_price_wei": int(receipt.get("effectiveGasPrice", gas_price)),
        "submit_to_receipt_ms": elapsed_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, help="Untracked .env with Sepolia RPC and testnet signer")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 5:
        raise ValueError("The methodology requires at least five repetitions.")
    if args.env_file:
        load_dotenv(args.env_file, override=False)

    rpc = os.getenv("SEPOLIA_RPC_URL", "").strip()
    private_key = os.getenv("DEPLOYER_PRIVATE_KEY", "").strip()
    if not rpc or not private_key:
        raise SystemExit("Set SEPOLIA_RPC_URL and DEPLOYER_PRIVATE_KEY; do not put secrets in tracked files.")
    deployment = json.loads(DEPLOYMENT.read_text(encoding="utf-8"))
    abi_data = json.loads(ABI_PATH.read_text(encoding="utf-8"))
    account = Account.from_key(private_key)
    if account.address.lower() != deployment["deployer"].lower():
        raise SystemExit("Configured signer does not match the administrator in the saved Sepolia deployment.")

    w3 = Web3(HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected() or w3.eth.chain_id != 11155111:
        raise SystemExit("RPC is not connected to Sepolia chain ID 11155111.")
    contract = w3.eth.contract(address=Web3.to_checksum_address(deployment["contracts"]["quarantineProxy"]), abi=abi_data["abi"])
    admin_role = contract.functions.DEFAULT_ADMIN_ROLE().call()
    oracle_role = contract.functions.ORACLE_ROLE().call()
    if not contract.functions.hasRole(admin_role, account.address).call():
        raise SystemExit("Signer does not have the deployed contract's administrator role.")
    if not contract.functions.hasRole(oracle_role, account.address).call():
        raise SystemExit("Signer does not have the deployed contract's oracle role.")

    model_version = 2
    model_hash = "0x" + hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    current_hash = contract.functions.modelHash(model_version).call()
    registration = None
    if not any(current_hash):
        fn = contract.functions.registerModel(model_version, bytes.fromhex(model_hash[2:]))
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        gas = fn.estimate_gas({"from": account.address})
        tx = fn.build_transaction({"from": account.address, "nonce": nonce, "chainId": w3.eth.chain_id,
                                   "gas": int(gas * 1.2), "gasPrice": w3.eth.gas_price})
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=360, poll_latency=1)
        if int(receipt.status) != 1:
            raise RuntimeError("Model v2 registration reverted on Sepolia")
        registration = {"tx_hash": Web3.to_hex(receipt.transactionHash), "block_number": int(receipt.blockNumber),
                        "gas_used": int(receipt.gasUsed)}
    elif Web3.to_hex(current_hash).lower() != model_hash.lower():
        raise SystemExit("Sepolia already has a different model hash at version 2; refusing to overwrite it.")

    device_hex = deployment["demo"]["devices"][0]["deviceId"]
    device_id = bytes.fromhex(device_hex[2:])
    if int(contract.functions.deviceStatus(device_id).call()) != 1:
        raise SystemExit("The saved Sepolia benchmark device is no longer Active; refusing to mutate another state.")
    balance_before = w3.eth.get_balance(account.address)
    samples = [send_and_measure(w3, contract, account, device_id, model_version, i + 1) for i in range(args.repeats)]
    balance_after = w3.eth.get_balance(account.address)
    values = [row["submit_to_receipt_ms"] for row in samples]
    output = {
        "network": "Sepolia",
        "chain_id": int(w3.eth.chain_id),
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_proxy": deployment["contracts"]["quarantineProxy"],
        "operation": "DeviceQuarantine.recordDecision, normal decision, model version 2",
        "device_id": device_hex,
        "model_version": model_version,
        "model_hash": model_hash,
        "model_registration": registration,
        "repetitions": len(samples),
        "samples": samples,
        "summary_ms": {
            "min": min(values), "median": sorted(values)[len(values) // 2],
            "mean": sum(values) / len(values), "max": max(values),
        },
        "testnet_balance_before_wei": balance_before,
        "testnet_balance_after_wei": balance_after,
        "measured_operation_cost_wei": balance_before - balance_after,
        "note": "Testnet-only writes; elapsed time includes provider submission and receipt polling, not finality guarantees.",
    }
    output_path = ROOT / "artifacts" / "sepolia_latency.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "samples": len(samples), "summary_ms": output["summary_ms"],
                      "registration_tx": registration["tx_hash"] if registration else "already registered"}, indent=2))


if __name__ == "__main__":
    main()
