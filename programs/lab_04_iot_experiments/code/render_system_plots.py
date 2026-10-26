"""Create report and presentation figures from retained, measured raw results."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
IMAGES = ROOT / "images"
IMAGES.mkdir(parents=True, exist_ok=True)


def load(name: str) -> dict:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def main() -> None:
    local = load("local_chain_experiments.json")
    sepolia = load("sepolia_latency.json")
    system = load("system_experiments.json")
    cost = load("cost_snapshot.json")
    security_api = load("security_api_checks.json")
    security_contract = load("security_contract_checks.json")
    lab3_project = ROOT.parent / "lab_03_iot_ml_integration"
    lab3_root = lab3_project / "code" if (lab3_project / "code").is_dir() else lab3_project
    ml_previous = json.loads((lab3_root / "artifacts" / "training_summary.json").read_text(encoding="utf-8"))
    metrics = pd.read_csv(ART / "model_metrics_group_bootstrap.csv")
    noise = pd.read_csv(ART / "robustness_noise.csv")
    learning = pd.read_csv(ART / "learning_curve_repeats.csv")
    gas = pd.DataFrame(local["gas_and_latency"])

    # 1. Receipt latency distributions: log axis keeps local and testnet scales visible.
    local_seconds = np.asarray(local["local_confirmation_latency"]) / 1000
    testnet_seconds = np.asarray([row["submit_to_receipt_ms"] for row in sepolia["samples"]]) / 1000
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    boxes = ax.boxplot([local_seconds, testnet_seconds], tick_labels=["Hardhat local", "Sepolia"], patch_artist=True)
    boxes["boxes"][0].set_facecolor("#64a8d7")
    boxes["boxes"][1].set_facecolor("#ed9a62")
    ax.set_yscale("log")
    ax.set_ylabel("Час від submit до receipt, с, log scale")
    ax.set_title("Розкид підтвердження 100 локальних і 5 Sepolia транзакцій")
    ax.grid(axis="y", alpha=.25, which="both")
    fig.tight_layout()
    fig.savefig(IMAGES / "transaction_latency.png", dpi=180)
    plt.close(fig)

    # 2. Gas use by the number of decisions already stored for the device.
    groups = gas.groupby("prior_records")["gas_used"]
    labels = sorted(groups.groups)
    samples = [groups.get_group(label).to_numpy() for label in labels]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.boxplot(samples, tick_labels=[str(x) for x in labels], showmeans=True)
    ax.set_xlabel("Записів для пристрою до вимірюваної операції")
    ax.set_ylabel("Gas використано")
    ax.set_title("Витрати recordDecision при зростанні історії пристрою")
    ax.grid(axis="y", alpha=.25)
    ax.annotate("Перший запис у новий mapping slot", xy=(1, max(samples[0])), xytext=(1.25, max(samples[0]) + 3500),
                arrowprops={"arrowstyle": "->", "lw": 1}, fontsize=8)
    fig.tight_layout()
    fig.savefig(IMAGES / "gas_by_prior_records.png", dpi=180)
    plt.close(fig)

    # 3. Load throughput and latency at 10, 50 and 100 concurrent users.
    load_rows = system["gateway_load"]
    users = [row["simulated_concurrent_users"] for row in load_rows]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    axes[0].plot(users, [row["throughput_requests_per_second"] for row in load_rows], marker="o")
    axes[0].set(xlabel="Одночасні користувачі", ylabel="Запитів/с", title="Пропускна здатність")
    axes[1].plot(users, [row["latency_ms"]["p95"] for row in load_rows], marker="o", color="#d35400")
    axes[1].axhline(200, color="black", linestyle="--", linewidth=1, label="NFR-06: 200 мс")
    axes[1].set(xlabel="Одночасні користувачі", ylabel="p95, мс", title="Затримка gateway API")
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=.25)
    fig.suptitle("Навантаження POST /api/gateway/check, 10 запитів на користувача")
    fig.tight_layout()
    fig.savefig(IMAGES / "gateway_load.png", dpi=180)
    plt.close(fig)

    # 4. Mean component cost after one warm-up, five measured end-to-end repetitions.
    stages = system["component_breakdown"]["mean_stage_ms"]
    stage_order = ["state_read", "canonicalization_and_hash", "model_prediction", "shap_explanation",
                   "sqlite_writes", "oracle_transaction_and_receipt", "sqlite_event_mirror"]
    stage_titles = ["Читання стану", "Канонізація/hash", "ML", "SHAP", "SQLite", "EVM tx/receipt", "Event mirror"]
    values = [stages[key] for key in stage_order]
    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(stage_titles, values, color=["#658db7", "#8fc0a9", "#d6ae66", "#c583a3", "#7bb4b0", "#cf6e52", "#8897b7"])
    ax.bar_label(bars, fmt="%.1f ms", padding=4, fontsize=8)
    ax.set_xlabel("Середній час компонента, мс")
    ax.set_title("Декомпозиція головного сценарію, 5 повторів після прогріву")
    ax.grid(axis="x", alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "scenario_components.png", dpi=180)
    plt.close(fig)

    # 5. Measured central path vs blockchain and public API path.
    values = [system["centralized_baseline"]["mean_ms"], stages["sum_instrumented_stages"],
              system["api_inference_e2e"]["mean_ms"]]
    labels = ["Централізовано\nSQLite + ML + SHAP", "Локальний EVM\nвиміряні компоненти", "API повний шлях\nHTTP + EVM"]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bars = ax.bar(labels, values, color=["#63a375", "#de984d", "#527ca3"])
    ax.bar_label(bars, fmt="%.1f мс", padding=3)
    ax.set_ylabel("Середня затримка, мс")
    ax.set_title("Вартість блокчейн-аудиту в затримці")
    ax.grid(axis="y", alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "centralized_vs_evm.png", dpi=180)
    plt.close(fig)

    # 6. Cost scenario, public fee snapshot, lower bounds on rollups.
    cost_rows = cost["chain_cost_estimates"]
    names = ["Ethereum L1", "Arbitrum execution", "Optimism execution", "Централізований VPS"]
    low = [row["estimated_monthly_execution_eur_30000_operations"] for row in cost_rows]
    high = [row["monthly_execution_plus_raw_calldata_sensitivity_eur"] for row in cost_rows]
    low.append(cost["centralized_hosting_scenario"]["assumed_monthly_host_eur"])
    high.append(low[-1])
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(x, low, color=["#b45145", "#5a91be", "#599b79", "#777777"])
    ax.errorbar(x[:3], low[:3], yerr=[np.zeros(3), np.asarray(high[:3]) - np.asarray(low[:3])], fmt="none", ecolor="black", capsize=4)
    ax.set_yscale("log")
    ax.set_xticks(x, names, rotation=10)
    ax.set_ylabel("Оцінка за 30 000 операцій, EUR, log scale")
    ax.set_title("Місячна оцінка: 1000 рішень на день")
    ax.grid(axis="y", alpha=.25, which="both")
    fig.text(.5, .015, "Штрихування для L2 - raw calldata sensitivity, не повна оцінка rollup fee.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(IMAGES / "monthly_costs.png", dpi=180)
    plt.close(fig)

    # 7. NFR compliance based on the referenced Lab 1 targets.
    rf = next(row for row in ml_previous["model_comparison"] if row["model"] == "Random Forest")
    model_p95 = ml_previous["prediction_latency"]["Random Forest"]["p95_ms"]
    gateway_p95 = system["gateway_nfr_1000_sequential"]["latency_ms"]["p95"]
    confirmation_p95 = float(np.percentile(local["local_confirmation_latency"], 95))
    api_p95 = system["api_inference_e2e"]["p95_ms"]
    audit = local["audit_coverage"]
    scale = local["nfr_device_scale"]
    integrity = next(row for row in security_api["checks"] if row["check"].startswith("100 контрольних"))
    nfr = [
        ("NFR-01 F1 ≥ 0,90", rf["f1_attack"], rf["f1_attack"] >= .90),
        ("NFR-02 Recall ≥ 0,90", rf["recall_attack"], rf["recall_attack"] >= .90),
        ("NFR-03 FPR ≤ 0,05", rf["false_positive_rate"], rf["false_positive_rate"] <= .05),
        ("NFR-04 ML p95 ≤ 250 мс", model_p95, model_p95 <= 250),
        ("NFR-05 reaction p95 ≤ 5 с", api_p95, api_p95 <= 5000),
        ("NFR-06 gateway p95 ≤ 200 мс", gateway_p95, gateway_p95 <= 200),
        ("NFR-07 version + hash 100 %", 100.0 if audit["all_have_model_version_2"] and audit["all_have_32_byte_input_hash"] else 0.0, audit["all_have_model_version_2"] and audit["all_have_32_byte_input_hash"]),
        ("NFR-08 1000 device lookups", scale["found_count"], scale["found_count"] == 1000),
        ("NFR-09 tampering 100 %", integrity["detection_rate"] * 100, integrity["detection_rate"] == 1.0),
    ]
    pd.DataFrame([{"nfr": name, "measured": value, "passed": passed} for name, value, passed in nfr]).to_csv(ART / "nfr_compliance.csv", index=False)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    y = np.arange(len(nfr))
    colors = ["#58a276" if passed else "#c65b50" for _, _, passed in nfr]
    ax.barh(y, [1] * len(nfr), color=colors)
    ax.set_yticks(y, [row[0] for row in nfr], fontsize=8)
    ax.set_xticks([0, 1], ["Не виконано", "Виконано"])
    ax.set_xlim(0, 1.08)
    ax.invert_yaxis()
    ax.set_title("Перевірка нефункціональних вимог ЛР 1")
    for i, (_, value, passed) in enumerate(nfr):
        ax.text(.04, i, f"виміряно: {value:.4g}" + ("" if passed else " - перевищення порога"), va="center", color="white", fontsize=8)
    ax.grid(axis="x", alpha=.15)
    fig.tight_layout()
    fig.savefig(IMAGES / "nfr_compliance.png", dpi=180)
    plt.close(fig)

    # 8. Security checks and outcome counts.
    categories = ["API attack/fault checks", "Smart-contract attack checks"]
    passed = [security_api["passed_checks"], security_contract["blocked_attacks"]]
    attempted = [security_api["attempted_checks"], security_contract["attempted_attacks"]]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(categories, attempted, color="#d5dbe0", label="Спроб")
    ax.bar(categories, passed, color="#599b79", label="Заблоковано / перевірено")
    ax.bar_label(ax.containers[1], labels=[f"{p}/{n}" for p, n in zip(passed, attempted)], padding=3)
    ax.set_ylabel("Кількість тестів")
    ax.set_title("Практична перевірка атак і відмов")
    ax.legend()
    ax.grid(axis="y", alpha=.2)
    fig.tight_layout()
    fig.savefig(IMAGES / "security_checks.png", dpi=180)
    plt.close(fig)

    summary = {
        "local_confirmation_ms": {"n": len(local["local_confirmation_latency"]), "mean": float(np.mean(local["local_confirmation_latency"])),
                                  "p95": confirmation_p95, "max": float(np.max(local["local_confirmation_latency"]))},
        "sepolia_confirmation_ms": sepolia["summary_ms"],
        "gas_by_prior_records": [{"prior_records": int(count), "n": int(len(values)), "mean": float(np.mean(values)),
                                  "sd": float(np.std(values, ddof=1)), "min": int(np.min(values)), "max": int(np.max(values))}
                                 for count, values in groups],
        "gateway_load": load_rows,
        "gateway_1000_sequential": system["gateway_nfr_1000_sequential"],
        "component_mean_ms": stages,
        "centralized_mean_ms": system["centralized_baseline"]["mean_ms"],
        "api_full_path_mean_ms": system["api_inference_e2e"]["mean_ms"],
        "monthly_costs": cost["chain_cost_estimates"],
        "central_hosting_scenario": cost["centralized_hosting_scenario"],
        "nfr_compliance": [{"id": name, "measured": value, "passed": passed} for name, value, passed in nfr],
        "api_security_checks": {"passed": security_api["passed_checks"], "total": security_api["attempted_checks"]},
        "contract_security_checks": {"blocked": security_contract["blocked_attacks"], "total": security_contract["attempted_attacks"]},
    }
    (ART / "lab4_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"generated_figures": 8, "nfr_passed": sum(item[2] for item in nfr), "nfr_total": len(nfr),
                      "security_api": [security_api["passed_checks"], security_api["attempted_checks"]],
                      "security_contract": [security_contract["blocked_attacks"], security_contract["attempted_attacks"]]}, indent=2))


if __name__ == "__main__":
    main()
