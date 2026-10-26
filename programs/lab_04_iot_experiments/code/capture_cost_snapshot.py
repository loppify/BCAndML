"""Fetch public fee/FX snapshots and calculate transparent 30-day estimates."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from web3 import HTTPProvider, Web3


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


def get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "NURE-lab4-cost-snapshot/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    endpoints = {
        "ethereum_mainnet": ("https://ethereum-rpc.publicnode.com", 1),
        "arbitrum_one": ("https://arb1.arbitrum.io/rpc", 42161),
        "optimism_mainnet": ("https://mainnet.optimism.io", 10),
    }
    snapshot = {}
    for name, (url, expected_chain) in endpoints.items():
        w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 20}))
        if not w3.is_connected() or w3.eth.chain_id != expected_chain:
            raise RuntimeError(f"Public fee endpoint did not return expected chain {expected_chain}: {name}")
        block = w3.eth.get_block("latest")
        snapshot[name] = {
            "chain_id": int(w3.eth.chain_id),
            "gas_price_wei": int(w3.eth.gas_price),
            "base_fee_per_gas_wei": int(block.get("baseFeePerGas") or 0),
            "block_number": int(block["number"]),
        }
    fx = get_json("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=eur")
    eth_eur = float(fx["ethereum"]["eur"])
    local = json.loads((ARTIFACTS / "local_chain_experiments.json").read_text(encoding="utf-8"))
    sepolia = json.loads((ARTIFACTS / "sepolia_latency.json").read_text(encoding="utf-8"))
    gas_samples = [int(row["gas_used"]) for row in sepolia["samples"]]
    contract_gas = int(sorted(gas_samples)[len(gas_samples) // 2])
    local_gas = [int(row["gas_used"]) for row in local["gas_and_latency"]]
    local_median_gas = int(sorted(local_gas)[len(local_gas) // 2])
    monthly_operations = 30_000
    main_gas_price = snapshot["ethereum_mainnet"]["gas_price_wei"]
    raw_calldata_upper_gas = 164 * 16
    cost_rows = []
    for name in ("ethereum_mainnet", "arbitrum_one", "optimism_mainnet"):
        gas_price = snapshot[name]["gas_price_wei"]
        execution_wei = contract_gas * gas_price
        l1_data_sensitivity_wei = 0 if name == "ethereum_mainnet" else raw_calldata_upper_gas * main_gas_price
        per_operation_eur = execution_wei * eth_eur / 1e18
        with_raw_calldata_eur = (execution_wei + l1_data_sensitivity_wei) * eth_eur / 1e18
        cost_rows.append({
            "network": name,
            "gas_units_proxy_measurement": contract_gas,
            "execution_cost_eur_per_operation": per_operation_eur,
            "estimated_monthly_execution_eur_30000_operations": per_operation_eur * monthly_operations,
            "raw_calldata_sensitivity_eur_per_operation": l1_data_sensitivity_wei * eth_eur / 1e18,
            "monthly_execution_plus_raw_calldata_sensitivity_eur": with_raw_calldata_eur * monthly_operations,
            "note": "Execution-only estimate; for L2, raw-call-data sensitivity is illustrative and not a total-fee quote or strict upper bound. Rollup compression, transaction envelope, operator fees and batch state are not fully modeled.",
        })
    result = {
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "fee_sources": {name: "public JSON-RPC eth_gasPrice and latest baseFeePerGas" for name in endpoints},
        "fx_source": "CoinGecko simple price API, ETH/EUR",
        "eth_eur": eth_eur,
        "market_fee_snapshot": snapshot,
        "measured_contract_gas": {
            "sepolia_uups_proxy_median": contract_gas,
            "sepolia_samples": gas_samples,
            "hardhat_local_contract_median": local_median_gas,
            "hardhat_local_samples": local_gas,
            "basis": "Use Sepolia proxy transaction gas as a closer analogue for deployed proxy operation; fee prices are a time-specific public snapshot.",
        },
        "monthly_workload": {"operations_per_day": 1000, "days": 30, "operations": monthly_operations},
        "l2_data_fee_method": {
            "fixed_call_data_bytes": 164,
            "raw_calldata_sensitivity_l1_gas": raw_calldata_upper_gas,
            "warning": "Illustrative raw-call-data sensitivity only. Arbitrum uses batch-compressed parent-chain data pricing; OP Stack fees include L1-data and operator components. Exact fees require a signed transaction and current chain-specific fee estimation.",
        },
        "chain_cost_estimates": cost_rows,
        "centralized_hosting_scenario": {
            "assumed_monthly_host_eur": 5.0,
            "monthly_operations": monthly_operations,
            "cost_eur_per_operation": 5.0 / monthly_operations,
            "note": "Illustrative low-cost single-server budget, not a measured quote; excludes backups, monitoring and engineering labor.",
        },
        "exclusions": ["deployment and model registration transactions", "API hosting and storage for chain scenarios", "operator labor", "rollup L1 batch fee uncertainty"],
    }
    output = ARTIFACTS / "cost_snapshot.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "eth_eur": eth_eur, "proxy_gas": contract_gas,
                      "estimates": [{"network": row["network"], "monthly_eur": row["estimated_monthly_execution_eur_30000_operations"],
                                     "monthly_with_calldata_sensitivity_eur": row["monthly_execution_plus_raw_calldata_sensitivity_eur"]} for row in cost_rows]}, indent=2))


if __name__ == "__main__":
    main()
