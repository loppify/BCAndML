"""Reproduce grouped model comparison, corruption and data-volume experiments."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score
import sys

ROOT = Path(__file__).resolve().parents[1]
LAB3_PROJECT = ROOT.parent / "lab_03_iot_ml_integration"
SOURCE = LAB3_PROJECT / "code" if (LAB3_PROJECT / "code").is_dir() else LAB3_PROJECT
sys.path.insert(0, str(SOURCE))

from app.data_pipeline import FEATURES, load_clean_data, make_partitions, signature_prediction
from app.train import pipeline_for


DATA = SOURCE / "data" / "raw" / "ton_iot_network.csv"
OUT = ROOT / "artifacts"
IMAGES = ROOT / "images"
OUT.mkdir(parents=True, exist_ok=True)
IMAGES.mkdir(parents=True, exist_ok=True)


def score(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    return {
        "f1_attack": float(f1_score(y, pred, zero_division=0)),
        "precision_attack": float(precision_score(y, pred, zero_division=0)),
        "recall_attack": float(recall_score(y, pred, zero_division=0)),
        "false_positive_rate": float(fp / (tn + fp)) if tn + fp else 0.0,
    }


def main() -> None:
    frame, data_info = load_clean_data(DATA)
    partitions = make_partitions(frame)
    train = partitions.train
    validation = partitions.validation
    test = partitions.test
    y = test["label"].to_numpy(dtype="int8")

    models = {
        "Random Forest": joblib.load(SOURCE / "models" / "random_forest_v2.joblib"),
        "Logistic Regression": joblib.load(SOURCE / "models" / "logistic_regression_v2.joblib"),
    }
    probabilities = {name: model.predict_proba(test[FEATURES])[:, list(model.named_steps["classifier"].classes_).index(1)]
                     for name, model in models.items()}
    predictions = {name: (p >= 0.5).astype("int8") for name, p in probabilities.items()}
    rules = np.asarray([
        signature_prediction(row.dst_port, row.src_pkts, row.conn_state)
        for row in test[["dst_port", "src_pkts", "conn_state"]].itertuples(index=False)
    ], dtype="int8")
    predictions["Signature rules"] = rules

    # Paired cluster bootstrap preserves dependence among flows from one source IP.
    groups = test["src_ip"].astype(str).to_numpy()
    unique_groups = np.unique(groups)
    group_indices = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(20261026)
    boot: dict[str, list[float]] = {name: [] for name in predictions}
    deltas = {"RF minus Logistic Regression": [], "RF minus signature rules": []}
    for _ in range(5000):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([group_indices[g] for g in sampled])
        values = {name: f1_score(y[idx], pred[idx], zero_division=0) for name, pred in predictions.items()}
        for name, value in values.items():
            boot[name].append(float(value))
        deltas["RF minus Logistic Regression"].append(values["Random Forest"] - values["Logistic Regression"])
        deltas["RF minus signature rules"].append(values["Random Forest"] - values["Signature rules"])

    model_rows = []
    for name, pred in predictions.items():
        metrics = score(y, pred)
        samples = np.asarray(boot[name])
        model_rows.append({"model": name, **metrics, "f1_ci95_low": float(np.quantile(samples, .025)),
                           "f1_ci95_high": float(np.quantile(samples, .975))})
    paired_rows = []
    for name, values in deltas.items():
        arr = np.asarray(values)
        prob_negative = float(np.mean(arr <= 0))
        prob_positive = float(np.mean(arr >= 0))
        paired_rows.append({"contrast": name, "mean_delta_f1": float(arr.mean()),
                            "ci95_low": float(np.quantile(arr, .025)),
                            "ci95_high": float(np.quantile(arr, .975)),
                            "two_sided_bootstrap_p": min(1.0, 2 * min(prob_negative, prob_positive))})

    # Grouped 5-repetition perturbation test. Noise is scaled by train-only feature SD.
    std = train[FEATURES].std(ddof=0).replace([np.inf, -np.inf], 0).fillna(0).to_numpy()
    noise_rows = []
    for level in (0.0, 0.05, 0.10, 0.20):
        for repeat in range(5):
            noise_rng = np.random.default_rng(3000 + int(level * 1000) * 10 + repeat)
            noise = noise_rng.normal(0, 1, size=(len(test), len(FEATURES))) * std * level
            noisy = test[FEATURES].to_numpy(dtype="float64") + noise
            noisy = np.where(np.isfinite(noisy), noisy, 0.0)
            noisy_frame = pd.DataFrame(noisy, columns=FEATURES)
            for name, model in models.items():
                p = model.predict_proba(noisy_frame)[:, list(model.named_steps["classifier"].classes_).index(1)]
                pred = (p >= .5).astype("int8")
                noise_rows.append({"noise_fraction_of_train_sd": level, "repeat": repeat + 1,
                                   "model": name, **score(y, pred)})
    noise_frame = pd.DataFrame(noise_rows)
    noise_frame.to_csv(OUT / "robustness_noise.csv", index=False)

    # Learning curve: fixed row counts are sampled only from train; validation groups stay untouched.
    learning_rows = []
    for fraction in (0.20, 0.40, 0.70, 1.0):
        count = max(2, int(np.ceil(len(train) * fraction)))
        for repeat in range(5):
            subset = train.sample(n=count, random_state=5000 + repeat * 101 + int(fraction * 1000))
            model = pipeline_for("Random Forest", {"n_estimators": 50, "max_depth": 18, "min_samples_leaf": 2})
            model.fit(subset[FEATURES], subset["label"].to_numpy())
            val_p = model.predict_proba(validation[FEATURES])[:, list(model.named_steps["classifier"].classes_).index(1)]
            train_p = model.predict_proba(subset[FEATURES])[:, list(model.named_steps["classifier"].classes_).index(1)]
            learning_rows.append({"fraction_of_train_rows": fraction, "rows": count,
                                  "source_groups": int(subset["src_ip"].nunique()),
                                  "training_rows": len(subset), "repeat": repeat + 1,
                                  "validation_f1": float(f1_score(validation["label"], val_p >= .5)),
                                  "train_f1": float(f1_score(subset["label"], train_p >= .5))})
    learning_frame = pd.DataFrame(learning_rows)
    learning_frame.to_csv(OUT / "learning_curve_repeats.csv", index=False)

    pd.DataFrame(model_rows).to_csv(OUT / "model_metrics_group_bootstrap.csv", index=False)
    pd.DataFrame(paired_rows).to_csv(OUT / "paired_group_bootstrap.csv", index=False)

    noise_summary = noise_frame.groupby(["noise_fraction_of_train_sd", "model"])[
        ["f1_attack", "recall_attack", "false_positive_rate"]
    ].agg(["mean", "std"]).round(6)
    noise_summary.columns = [f"{metric}_{stat}" for metric, stat in noise_summary.columns]
    learning_summary = learning_frame.groupby("fraction_of_train_rows")[
        ["training_rows", "source_groups", "validation_f1", "train_f1"]
    ].agg(["mean", "std"]).round(6)
    learning_summary.columns = [f"{metric}_{stat}" for metric, stat in learning_summary.columns]

    summary = {
        "dataset": data_info,
        "partitions": partitions.split_info,
        "heldout_metrics_cluster_bootstrap": model_rows,
        "paired_f1_group_bootstrap": paired_rows,
        "robustness_summary": noise_summary.reset_index().to_dict(orient="records"),
        "learning_curve_summary": learning_summary.reset_index().to_dict(orient="records"),
        "repetitions": {"group_bootstrap_draws": 5000, "noise_per_level": 5, "learning_curve_per_level": 5},
    }
    (OUT / "ml_experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Figures: paired confidence intervals and robust performance.
    fig, ax = plt.subplots(figsize=(9, 5))
    xs = np.arange(len(model_rows))
    means = [r["f1_attack"] for r in model_rows]
    lows = [r["f1_ci95_low"] for r in model_rows]
    highs = [r["f1_ci95_high"] for r in model_rows]
    ax.errorbar(xs, means, yerr=[np.array(means) - lows, np.array(highs) - means], fmt="o", capsize=5)
    ax.set_xticks(xs, [r["model"] for r in model_rows], rotation=12)
    ax.set_ylabel("F1 атаки (кластерний bootstrap CI 95 %)")
    ax.set_ylim(-0.03, 1.04)
    ax.set_title("Порівняння моделей на тих самих held-out групах")
    ax.grid(axis="y", alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "group_bootstrap_model_ci.png", dpi=180)
    plt.close(fig)

    means_noise = noise_frame.groupby(["noise_fraction_of_train_sd", "model"])["f1_attack"].agg(["mean", "std"]).reset_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    for name, group in means_noise.groupby("model"):
        ax.errorbar(group["noise_fraction_of_train_sd"] * 100, group["mean"], yerr=group["std"], marker="o", capsize=4, label=name)
    ax.set(xlabel="Середньоквадратичне спотворення, % від train SD", ylabel="F1 атаки",
           title="Стійкість моделей до контрольованого шуму")
    ax.legend()
    ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "noise_robustness.png", dpi=180)
    plt.close(fig)

    learning = learning_frame.groupby("fraction_of_train_rows")["validation_f1"].agg(["mean", "std"]).reset_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.errorbar(learning["fraction_of_train_rows"] * 100, learning["mean"], yerr=learning["std"], marker="o", capsize=4)
    ax.set(xlabel="Використана частка train-рядків, %", ylabel="F1 на незмінному validation",
           title="Залежність якості від обсягу навчальних даних")
    ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "training_volume.png", dpi=180)
    plt.close(fig)

    delta_frame = pd.DataFrame(paired_rows)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    y_pos = np.arange(len(delta_frame))
    ax.errorbar(delta_frame["mean_delta_f1"], y_pos,
                xerr=[delta_frame["mean_delta_f1"] - delta_frame["ci95_low"], delta_frame["ci95_high"] - delta_frame["mean_delta_f1"]],
                fmt="o", capsize=5)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y_pos, delta_frame["contrast"])
    ax.set_xlabel("Різниця F1 (RF мінус контрольний метод), 95 % CI")
    ax.set_title("Парне порівняння зі збереженням source-group структури")
    ax.grid(axis="x", alpha=.25)
    fig.tight_layout()
    fig.savefig(IMAGES / "paired_model_differences.png", dpi=180)
    plt.close(fig)

    print(json.dumps({"summary": str(OUT / "ml_experiment_summary.json"), "plots": [
        str(IMAGES / "group_bootstrap_model_ci.png"), str(IMAGES / "noise_robustness.png"),
        str(IMAGES / "training_volume.png"), str(IMAGES / "paired_model_differences.png")],
        "heldout_groups": len(unique_groups), "repetitions_noise": 5, "repetitions_learning_curve": 5}, indent=2))


if __name__ == "__main__":
    main()
