"""Web3 client for the Lab 2 contracts and the real Random Forest oracle."""
from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import HTTPProvider, Web3
from web3.exceptions import ContractLogicError, TimeExhausted

from app.data_pipeline import canonical_json, sha256_hex
from app.settings import Settings, settings


LOGGER = logging.getLogger("iot_ids.blockchain")
EVENTS = {
    "registry": ("DeviceRegistered", "OwnerChanged"),
    "access_control": ("AccessGranted", "AccessRevoked"),
    "quarantine": (
        "ModelRegistered", "DecisionRecorded", "DeviceQuarantined", "QuarantineReleased",
        "OracleChanged", "Paused", "Unpaused",
    ),
}


def _hex(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return Web3.to_hex(value)
    if hasattr(value, "hex") and not isinstance(value, str):
        try:
            return value.hex()
        except Exception:
            return str(value)
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return _hex(value)


class BlockchainService:
    def __init__(self, config: Settings = settings, repository=None):
        self.config = config
        self.repository = repository
        self.w3 = Web3(HTTPProvider(config.rpc_url, request_kwargs={"timeout": 20}))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to the EVM provider at {config.rpc_url}")
        self.deployment = json.loads(config.deployment_path.read_text(encoding="utf-8"))
        self.chain_id = int(self.w3.eth.chain_id)
        self.contracts = self._load_contracts()
        self.start_block = int(self.deployment.get("deployment_block", 0))

    def _artifact(self, source_path: str) -> dict[str, Any]:
        path = self.config.code_root / "build" / "hardhat-artifacts" / source_path
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_contracts(self) -> dict[str, Any]:
        addresses = self.deployment["contracts"]
        artifact_paths = {
            "registry": "contracts/DeviceRegistry.sol/DeviceRegistry.json",
            "access_control": "contracts/AccessControl.sol/AccessControl.json",
            "quarantine": "contracts/DeviceQuarantine.sol/DeviceQuarantine.json",
        }
        result = {}
        for name, artifact_path in artifact_paths.items():
            artifact = self._artifact(artifact_path)
            result[name] = self.w3.eth.contract(address=Web3.to_checksum_address(addresses[name]), abi=artifact["abi"])
        return result

    @property
    def roles(self) -> dict[str, str]:
        return {key: Web3.to_checksum_address(value) for key, value in self.deployment["roles"].items()}

    @property
    def addresses(self) -> dict[str, str]:
        return {key: Web3.to_checksum_address(value) for key, value in self.deployment["contracts"].items()}

    def public_config(self) -> dict[str, Any]:
        card_path = self.config.model_card_path
        card = json.loads(card_path.read_text(encoding="utf-8"))
        registered_hash = self.contracts["quarantine"].functions.modelHash(self.config.model_version).call()
        return {
            "chain_id": self.chain_id,
            "expected_chain_id": self.config.chain_id,
            "contracts": self.addresses,
            "roles": self.roles,
            "start_block": self.start_block,
            "model_version": self.config.model_version,
            "model_hash": card["artifact_sha256"],
            "registered_model_hash": Web3.to_hex(registered_hash),
            "confidence_threshold_bps": self.config.confidence_threshold_bps,
            "explorer_base_url": self.config.explorer_base_url,
        }

    def is_admin(self, address: str) -> bool:
        contract = self.contracts["quarantine"]
        role = contract.functions.DEFAULT_ADMIN_ROLE().call()
        return bool(contract.functions.hasRole(role, Web3.to_checksum_address(address)).call())

    def device_exists(self, device_id: str) -> bool:
        return bool(self.contracts["registry"].functions.exists(Web3.to_bytes(hexstr=device_id)).call())

    def device_owner(self, device_id: str) -> str:
        owner = self.contracts["registry"].functions.ownerOfDevice(Web3.to_bytes(hexstr=device_id)).call()
        return Web3.to_checksum_address(owner)

    def device_status(self, device_id: str) -> dict[str, Any]:
        contract = self.contracts["quarantine"]
        enum_value = int(contract.functions.deviceStatus(Web3.to_bytes(hexstr=device_id)).call())
        state = ("Unregistered", "Active", "Quarantined")[enum_value]
        return {"device_id": device_id.lower(), "state": state, "status_code": enum_value}

    def gateway_can_interact(self, device_id: str, actor: str) -> bool:
        gateway = self.roles["gateway"]
        return bool(self.contracts["access_control"].functions.canInteract(
            Web3.to_bytes(hexstr=device_id), Web3.to_checksum_address(actor)
        ).call({"from": gateway}))

    def prepare_owner_transaction(self, action: str, payload: dict[str, Any], sender: str) -> dict[str, Any]:
        sender = Web3.to_checksum_address(sender)
        if self.chain_id != self.config.chain_id:
            raise ValueError(f"Wrong EVM chain: expected {self.config.chain_id}, got {self.chain_id}.")
        if action == "register_device":
            local_name = str(payload.get("local_name", "Virtual IoT device")).strip()[:80]
            salt = Web3.to_hex(secrets.token_bytes(32))
            metadata = {"local_name": local_name, "schema": "device-metadata-v1"}
            metadata_hash = Web3.to_hex(Web3.keccak(canonical_json(metadata)))
            encoded_id = self.w3.codec.encode(["address", "bytes32"], [sender, salt])
            device_id = Web3.to_hex(Web3.keccak(encoded_id))
            function = self.contracts["registry"].functions.registerDevice(Web3.to_bytes(hexstr=salt), Web3.to_bytes(hexstr=metadata_hash))
            extra = {"device_id": device_id.lower(), "local_name": local_name, "owner_address": sender, "metadata_hash": metadata_hash}
            target = self.addresses["registry"]
        elif action == "grant_access":
            device_id = str(payload["device_id"])
            actor = Web3.to_checksum_address(payload["actor"])
            valid_until = int(payload["valid_until"])
            function = self.contracts["access_control"].functions.grantAccess(
                Web3.to_bytes(hexstr=device_id), actor, valid_until
            )
            extra = {"device_id": device_id.lower(), "actor": actor, "valid_until": valid_until}
            target = self.addresses["access_control"]
        elif action == "revoke_access":
            device_id = str(payload["device_id"])
            actor = Web3.to_checksum_address(payload["actor"])
            function = self.contracts["access_control"].functions.revokeAccess(Web3.to_bytes(hexstr=device_id), actor)
            extra = {"device_id": device_id.lower(), "actor": actor}
            target = self.addresses["access_control"]
        elif action == "release_quarantine":
            device_id = str(payload["device_id"])
            function = self.contracts["quarantine"].functions.releaseQuarantine(Web3.to_bytes(hexstr=device_id))
            extra = {"device_id": device_id.lower()}
            target = self.addresses["quarantine"]
        else:
            raise ValueError(f"Unsupported transaction action: {action}")
        return {"to": target, "data": function._encode_transaction_data(), "chain_id": self.chain_id,
                "action": action, "extra": extra}

    def confirm_wallet_transaction(self, tx_hash: str, action: str, extra: dict[str, Any]) -> dict[str, Any]:
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        status = int(receipt["status"])
        if status != 1:
            raise ValueError("The transaction was mined but reverted. Check wallet role, chain and device state.")
        result = {"tx_hash": Web3.to_hex(receipt["transactionHash"]), "block_number": int(receipt["blockNumber"]),
                  "status": "confirmed", "action": action}
        result.update(extra)
        if action == "register_device" and self.repository is not None:
            device_id = extra["device_id"]
            if not self.device_exists(device_id):
                raise ValueError("The device registration receipt has no matching on-chain registry entry.")
            owner = self.device_owner(device_id)
            metadata_hash = Web3.to_hex(self.contracts["registry"].functions.metadataHashOf(
                Web3.to_bytes(hexstr=device_id)
            ).call()).lower()
            if owner.lower() != str(extra["owner_address"]).lower() or metadata_hash != str(extra["metadata_hash"]).lower():
                raise ValueError("The local device metadata does not match the registry event and current owner.")
            self.repository.save_device(device_id, extra["local_name"], owner, metadata_hash)
        self.refresh_event_mirror()
        return result

    def send_decision(self, device_id: str, is_attack: bool, confidence_bps: int,
                      model_version: int, input_hash: str) -> dict[str, Any]:
        quarantine = self.contracts["quarantine"]
        registered_model_bytes = quarantine.functions.modelHash(model_version).call()
        if not any(registered_model_bytes):
            raise ValueError(f"Model version {model_version} is not registered in the contract.")
        registered_hash = Web3.to_hex(registered_model_bytes).lower()
        card = json.loads(self.config.model_card_path.read_text(encoding="utf-8"))
        if registered_hash != str(card["artifact_sha256"]).lower():
            raise ValueError("On-chain model hash does not match the local model artifact.")

        device_bytes = Web3.to_bytes(hexstr=device_id)
        input_bytes = Web3.to_bytes(hexstr=input_hash)
        oracle = self.roles["oracle"]
        private_key = self.config.oracle_private_key
        if private_key:
            account = Account.from_key(private_key)
            if account.address.lower() != oracle.lower():
                raise ValueError("ORACLE_PRIVATE_KEY address differs from the oracle role in deployment configuration.")
        else:
            unlocked = {address.lower() for address in self.w3.eth.accounts}
            if oracle.lower() not in unlocked:
                raise ValueError("Set ORACLE_PRIVATE_KEY in .env or expose the local oracle account through the provider.")

        function = quarantine.functions.recordDecision(device_bytes, bool(is_attack), int(confidence_bps), int(model_version), input_bytes)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                # The contract's processedInputHash and this lookup make resubmission idempotent.
                existing = self.find_decision(device_id, input_hash)
                if existing:
                    return {"tx_hash": existing["tx_hash"], "block_number": existing["block_number"], "replayed": True}
                if private_key:
                    transaction = function.build_transaction({
                        "from": account.address,
                        "nonce": self.w3.eth.get_transaction_count(account.address),
                        "chainId": self.chain_id,
                        "gas": int(function.estimate_gas({"from": account.address}) * 1.2),
                        "gasPrice": self.w3.eth.gas_price,
                    })
                    signed = account.sign_transaction(transaction)
                    tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                else:
                    tx_hash = function.transact({"from": oracle})
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
                if int(receipt["status"]) != 1:
                    raise ValueError("The oracle transaction reverted on-chain.")
                return {"tx_hash": Web3.to_hex(receipt["transactionHash"]),
                        "block_number": int(receipt["blockNumber"]), "replayed": False}
            except ContractLogicError:
                raise
            except ValueError as exc:
                if "reverted" in str(exc).lower() or "execution reverted" in str(exc).lower():
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc
            if attempt < 2:
                LOGGER.warning("Oracle RPC attempt %s/3 failed for input %s: %s", attempt + 1, input_hash, last_error)
                try:
                    existing = self.find_decision(device_id, input_hash)
                    if existing:
                        return {"tx_hash": existing["tx_hash"], "block_number": existing["block_number"], "replayed": True}
                except Exception:
                    pass
                time.sleep(0.5 * (2 ** attempt))
        raise ConnectionError(f"Oracle transaction failed after three attempts: {last_error}") from last_error

    def find_decision(self, device_id: str, input_hash: str) -> dict[str, Any] | None:
        event = self.contracts["quarantine"].events.DecisionRecorded
        logs = event.get_logs(from_block=self.start_block, to_block="latest",
                              argument_filters={"deviceId": Web3.to_bytes(hexstr=device_id)})
        wanted_hash = input_hash.lower()
        logs = [log for log in logs if Web3.to_hex(log["args"]["inputHash"]).lower() == wanted_hash]
        if not logs:
            return None
        log = sorted(logs, key=lambda item: (item["blockNumber"], item["logIndex"]))[0]
        return {"tx_hash": Web3.to_hex(log["transactionHash"]), "block_number": int(log["blockNumber"]),
                "input_hash": Web3.to_hex(log["args"]["inputHash"]).lower()}

    def read_events(self, from_block: int | None = None) -> list[dict[str, Any]]:
        start = self.start_block if from_block is None else int(from_block)
        events: list[dict[str, Any]] = []
        for contract_name, event_names in EVENTS.items():
            contract = self.contracts[contract_name]
            for event_name in event_names:
                event_class = getattr(contract.events, event_name)
                try:
                    logs = event_class.get_logs(from_block=start, to_block="latest")
                except Exception as exc:
                    LOGGER.warning("Could not read %s.%s logs: %s", contract_name, event_name, exc)
                    continue
                for log in logs:
                    args = _jsonable(dict(log["args"]))
                    normalized = {key[0].lower() + key[1:]: value for key, value in args.items()}
                    device_id = normalized.get("deviceId")
                    model_version = normalized.get("version", normalized.get("modelVersion"))
                    events.append({
                        "event_name": event_name,
                        "tx_hash": Web3.to_hex(log["transactionHash"]),
                        "log_index": int(log["logIndex"]),
                        "block_number": int(log["blockNumber"]),
                        "device_id": device_id.lower() if isinstance(device_id, str) else None,
                        "model_version": int(model_version) if model_version is not None else None,
                        "args": normalized,
                    })
        return sorted(events, key=lambda event: (event["block_number"], event["log_index"]))

    def refresh_event_mirror(self) -> list[dict[str, Any]]:
        events = self.read_events()
        if self.repository is not None:
            self.repository.refresh_events(events)
        return events

    def audit_history(self, limit: int = 100) -> list[dict[str, Any]]:
        events = self.read_events()
        return events[-limit:][::-1]

    def registered_devices(self) -> list[dict[str, Any]]:
        contract = self.contracts["registry"]
        logs = contract.events.DeviceRegistered.get_logs(from_block=self.start_block, to_block="latest")
        devices = []
        seen: set[str] = set()
        for log in logs:
            device_id = Web3.to_hex(log["args"]["deviceId"]).lower()
            if device_id in seen:
                continue
            seen.add(device_id)
            owner = Web3.to_checksum_address(log["args"]["owner"])
            metadata_hash = Web3.to_hex(log["args"]["metadataHash"]).lower()
            details = self.repository.device(device_id) if self.repository else None
            devices.append({
                "device_id": device_id,
                "owner_address": owner,
                "metadata_hash": metadata_hash,
                "local_name": details["local_name"] if details else "Virtual IoT device",
                **self.device_status(device_id),
            })
        return devices

    def network_status(self) -> dict[str, Any]:
        return {"connected": self.w3.is_connected(), "chain_id": self.chain_id,
                "expected_chain_id": self.config.chain_id, "block_number": int(self.w3.eth.block_number)}
