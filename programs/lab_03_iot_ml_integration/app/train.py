"""Reproducible grouped training, tuning, evaluation and figure generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

from app.data_pipeline import (
    FEATURES,
    RANDOM_SEED,
    DataPartitions,
    load_clean_data,
    make_demo_flows,
    make_partitions,
    signature_prediction,
)
from app.settings import settings


sns.set_theme(style="whitegrid", context="notebook")


def pipeline_for(model_name: str, params: dict[str, Any] | None = None) -> Pipeline:
    params = params or {}
    if model_name == "Random Forest":
        classifier = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            max_depth=params.get("max_depth", 18),
            min_samples_leaf=int(params.get("min_samples_leaf", 2)),
            class_weight="balanced_subsample",
            random_state=RANDOM_SEED,
            n_jobs=-1,
        )
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
            ("classifier", classifier),
        ])
    if model_name == "Logistic Regression":
        classifier = LogisticRegression(
            C=float(params.get("C", 1.0)),
            class_weight="balanced",
            max_iter=1000,
            solver="lbfgs",
            random_state=RANDOM_SEED,
        )
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("classifier", classifier),
        ])
    raise ValueError(f"Unknown model: {model_name}")


def metrics_for(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    predictions = (probabilities >= 0.5).astype("int8")
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    return {
        "accuracy": float(accuracy_score(y_true, predictions)),
        "precision_attack": float(precision_score(y_true, predictions, zero_division=0)),
        "recall_attack": float(recall_score(y_true, predictions, zero_division=0)),
        "f1_attack": float(f1_score(y_true, predictions, zero_division=0)),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)) if len(np.unique(y_true)) > 1 else float("nan"),
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=[0, 1]).tolist(),
    }


def positive_probability(model: Pipeline, X: pd.DataFrame) -> np.ndarray:
    classifier = model.named_steps["classifier"]
    classes = list(classifier.classes_)
    return model.predict_proba(X[FEATURES])[:, classes.index(1)]


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _search_hyperparameters(partitions: DataPartitions) -> tuple[dict[str, Any], float, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    train = partitions.train
    validation = partitions.validation
    x_train, y_train = train[FEATURES], train["label"].to_numpy()
    x_validation, y_validation = validation[FEATURES], validation["label"].to_numpy()
    rows: list[dict[str, Any]] = []

    best_rf: dict[str, Any] | None = None
    best_rf_score = -math.inf
    for n_estimators in (50, 100):
        for max_depth in (12, 18):
            params = {"n_estimators": n_estimators, "max_depth": max_depth, "min_samples_leaf": 2}
            model = pipeline_for("Random Forest", params)
            start = time.perf_counter()
            model.fit(x_train, y_train)
            elapsed = time.perf_counter() - start
            probabilities = positive_probability(model, x_validation)
            score = metrics_for(y_validation, probabilities)
            rows.append({"model": "Random Forest", **params, "validation_f1": score["f1_attack"],
                         "validation_precision": score["precision_attack"], "validation_recall": score["recall_attack"],
                         "validation_pr_auc": score["pr_auc"], "fit_seconds": elapsed})
            if (score["f1_attack"], score["pr_auc"]) > (best_rf_score, -math.inf):
                best_rf, best_rf_score = params, score["f1_attack"]

    best_lr: dict[str, Any] | None = None
    best_lr_score = -math.inf
    lr_rows: list[dict[str, Any]] = []
    for c_value in (0.2, 1.0, 5.0):
        params = {"C": c_value}
        model = pipeline_for("Logistic Regression", params)
        start = time.perf_counter()
        model.fit(x_train, y_train)
        elapsed = time.perf_counter() - start
        probabilities = positive_probability(model, x_validation)
        score = metrics_for(y_validation, probabilities)
        row = {"model": "Logistic Regression", **params, "validation_f1": score["f1_attack"],
               "validation_precision": score["precision_attack"], "validation_recall": score["recall_attack"],
               "validation_pr_auc": score["pr_auc"], "fit_seconds": elapsed}
        rows.append(row)
        lr_rows.append(row)
        if score["f1_attack"] > best_lr_score:
            best_lr, best_lr_score = params, score["f1_attack"]

    assert best_rf is not None and best_lr is not None
    return best_rf, best_rf_score, rows, best_lr, lr_rows


def _cross_validation(model_name: str, params: dict[str, Any], frame: pd.DataFrame) -> list[dict[str, float]]:
    X, y, groups = frame[FEATURES], frame["label"].to_numpy(), frame["src_ip"].to_numpy()
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED + 2)
    results = []
    for fold, (fit_index, validation_index) in enumerate(splitter.split(X, y, groups), start=1):
        model = pipeline_for(model_name, params)
        model.fit(X.iloc[fit_index], y[fit_index])
        probabilities = positive_probability(model, X.iloc[validation_index])
        row = metrics_for(y[validation_index], probabilities)
        results.append({"fold": fold, **{key: row[key] for key in ("precision_attack", "recall_attack", "f1_attack", "pr_auc")}})
    return results


def _rule_probability(frame: pd.DataFrame) -> np.ndarray:
    return np.asarray([
        signature_prediction(row.dst_port, row.src_pkts, row.conn_state)
        for row in frame[["dst_port", "src_pkts", "conn_state"]].itertuples(index=False)
    ], dtype="float64")


def _cross_validate_rules(frame: pd.DataFrame) -> list[dict[str, float]]:
    X, y, groups = frame[FEATURES], frame["label"].to_numpy(), frame["src_ip"].to_numpy()
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED + 2)
    rows = []
    for fold, (_, validation_index) in enumerate(splitter.split(X, y, groups), start=1):
        validation = frame.iloc[validation_index]
        score = metrics_for(y[validation_index], _rule_probability(validation))
        rows.append({"fold": fold, **{key: score[key] for key in ("precision_attack", "recall_attack", "f1_attack", "pr_auc")}})
    return rows


def _latency_stats(model: Pipeline, X: pd.DataFrame, repeats: int = 500) -> dict[str, float]:
    sample = X[FEATURES].iloc[[0]]
    model.predict_proba(sample)
    samples = np.empty(repeats, dtype="float64")
    for _ in range(repeats):
        start = time.perf_counter_ns()
        model.predict_proba(sample)
        samples[_] = (time.perf_counter_ns() - start) / 1_000_000
    return {"mean_ms": float(np.mean(samples)), "p95_ms": float(np.percentile(samples, 95))}


def _save_plots(
    output_dir: Path,
    partitions: DataPartitions,
    fitted: dict[str, Pipeline],
    test_probabilities: dict[str, np.ndarray],
    test_metrics: dict[str, dict[str, Any]],
    cv_rows: dict[str, list[dict[str, float]]],
    tuning_rows: list[dict[str, Any]],
    error_frame: pd.DataFrame,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    def save(name: str) -> None:
        target = output_dir / name
        plt.tight_layout()
        plt.savefig(target, dpi=180, bbox_inches="tight")
        plt.close()
        paths[name] = str(target)

    test = partitions.test
    y_test = test["label"].to_numpy()
    rf_model = fitted["Random Forest"]
    rf_prob = test_probabilities["Random Forest"]
    rf_pred = (rf_prob >= 0.5).astype(int)

    # 1. Learning curves over increasing, reproducible training-set sizes.
    train = partitions.train
    val = partitions.validation
    learning_rows = []
    for fraction in (0.2, 0.4, 0.7, 1.0):
        if fraction >= 0.999:
            subset = train
        else:
            _, subset = train_test_split(
                train,
                test_size=fraction,
                random_state=RANDOM_SEED,
                stratify=train["label"],
            )
        curve_model = pipeline_for("Random Forest", rf_model.named_steps["classifier"].get_params())
        start = time.perf_counter()
        curve_model.fit(subset[FEATURES], subset["label"])
        train_prob = positive_probability(curve_model, subset[FEATURES])
        val_prob = positive_probability(curve_model, val[FEATURES])
        learning_rows.append({
            "training_rows": len(subset),
            "training_fraction": fraction,
            "train_f1": f1_score(subset["label"], train_prob >= 0.5, zero_division=0),
            "validation_f1": f1_score(val["label"], val_prob >= 0.5, zero_division=0),
            "fit_seconds": time.perf_counter() - start,
        })
    learning = pd.DataFrame(learning_rows)
    learning.to_csv(output_dir / "learning_curve_points.csv", index=False)
    plt.figure(figsize=(7.5, 4.5))
    plt.plot(learning["training_rows"], learning["train_f1"], marker="o", label="Train F1")
    plt.plot(learning["training_rows"], learning["validation_f1"], marker="o", label="Validation F1")
    plt.xlabel("Кількість навчальних записів")
    plt.ylabel("F1 для класу атаки")
    plt.title("Навчальна крива Random Forest")
    plt.legend()
    save("learning_curve.png")

    # 2. Confusion matrix.
    cm = confusion_matrix(y_test, rf_pred, labels=[0, 1])
    plt.figure(figsize=(5.5, 4.8))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", cbar=False,
                xticklabels=["Нормальний", "Атака"], yticklabels=["Нормальний", "Атака"])
    plt.xlabel("Передбачений клас")
    plt.ylabel("Фактичний клас")
    plt.title("Матриця помилок Random Forest")
    save("confusion_matrix.png")

    # 3. ROC curve.
    plt.figure(figsize=(6.3, 4.8))
    for name, probabilities in test_probabilities.items():
        fpr, tpr, _ = roc_curve(y_test, probabilities)
        plt.plot(fpr, tpr, label=f"{name} (AUC={roc_auc_score(y_test, probabilities):.3f})")
    plt.plot([0, 1], [0, 1], "--", color="gray", linewidth=1)
    plt.xlabel("False positive rate")
    plt.ylabel("Recall")
    plt.title("ROC-криві на відкладених групах")
    plt.legend(fontsize=8)
    save("roc_curve.png")

    # 4. Precision-recall curve.
    plt.figure(figsize=(6.3, 4.8))
    for name, probabilities in test_probabilities.items():
        precision, recall, _ = precision_recall_curve(y_test, probabilities)
        plt.plot(recall, precision, label=f"{name} (AP={average_precision_score(y_test, probabilities):.3f})")
    plt.axhline(float(np.mean(y_test)), linestyle="--", color="gray", label="Частка позитивного класу")
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Precision-recall криві")
    plt.legend(fontsize=8)
    save("precision_recall.png")

    # 5. Global feature importance and SHAP summary.
    tree = rf_model.named_steps["classifier"]
    importances = pd.DataFrame({"feature": FEATURES, "importance": tree.feature_importances_}).sort_values("importance", ascending=True)
    importances.to_csv(output_dir / "feature_importance.csv", index=False)
    plt.figure(figsize=(7.5, 5.3))
    plt.barh(importances["feature"], importances["importance"], color="#4776a8")
    plt.xlabel("Середня важливість розбиття дерев")
    plt.title("Важливість ознак Random Forest")
    save("feature_importance.png")

    shap_status = "not available"
    try:
        import shap
        sample = test[FEATURES].sample(n=min(300, len(test)), random_state=RANDOM_SEED)
        transformed = rf_model.named_steps["imputer"].transform(sample)
        explainer = shap.TreeExplainer(tree)
        values = explainer.shap_values(transformed, check_additivity=False)
        if isinstance(values, list):
            values = values[1]
        elif np.asarray(values).ndim == 3:
            values = np.asarray(values)[:, :, 1]
        shap.summary_plot(values, sample, feature_names=FEATURES, plot_type="bar", show=False, max_display=10)
        plt.title("SHAP: глобальний внесок ознак у клас атаки")
        save("shap_summary.png")
        np.savez_compressed(output_dir / "shap_test_sample.npz", values=np.asarray(values), features=sample.to_numpy())
        shap_status = "TreeExplainer calculated on held-out samples"
    except Exception as exc:  # summary importance above remains an independent graph.
        shap_status = f"TreeExplainer unavailable: {type(exc).__name__}: {exc}"
        plt.figure(figsize=(7.5, 4.2))
        plt.text(0.02, 0.9, "SHAP could not be calculated in this environment", fontsize=13)
        plt.text(0.02, 0.76, shap_status, fontsize=8, wrap=True)
        plt.axis("off")
        save("shap_summary.png")

    # 6. Model comparison with group-fold spread.
    names = ["Signature rules", "Logistic Regression", "Random Forest"]
    means, deviations, test_values = [], [], []
    for name in names:
        fold_scores = [row["f1_attack"] for row in cv_rows[name]]
        means.append(float(np.mean(fold_scores)))
        deviations.append(float(np.std(fold_scores, ddof=1)) if len(fold_scores) > 1 else 0.0)
        test_values.append(test_metrics[name]["f1_attack"])
    x = np.arange(len(names))
    plt.figure(figsize=(7.5, 4.8))
    plt.bar(x - 0.18, means, width=0.36, yerr=deviations, capsize=4, label="5-fold group CV mean ± SD")
    plt.bar(x + 0.18, test_values, width=0.36, label="Held-out test")
    plt.xticks(x, names, rotation=12)
    plt.ylabel("F1 для класу атаки")
    plt.ylim(0, 1.05)
    plt.title("Порівняння методів і розкиду за груповими фолдами")
    plt.legend(fontsize=8)
    save("model_comparison.png")

    # 7. Hyperparameter effect.
    trials = pd.DataFrame(tuning_rows)
    rf_trials = trials.loc[trials["model"] == "Random Forest"].copy()
    rf_trials["configuration"] = rf_trials.apply(
        lambda row: f"n={int(row['n_estimators'])}, depth={int(row['max_depth'])}", axis=1
    )
    plt.figure(figsize=(7.5, 4.6))
    sns.barplot(data=rf_trials, x="configuration", y="validation_f1", color="#6c9f78")
    plt.xlabel("Параметри Random Forest")
    plt.ylabel("Validation F1")
    plt.title("Вплив кількості дерев і глибини")
    save("hyperparameter_impact.png")

    # 8. Error analysis by held-out source group, anonymized.
    errors = error_frame.copy()
    errors["prediction"] = rf_pred
    errors["error_type"] = np.select(
        [(errors["label"] == 0) & (errors["prediction"] == 1),
         (errors["label"] == 1) & (errors["prediction"] == 0)],
        ["False positive", "False negative"],
        default="Correct",
    )
    group_map = {source: f"Тестова група {index:02d}" for index, source in enumerate(sorted(errors["src_ip"].unique()), start=1)}
    errors["source_group"] = errors["src_ip"].map(group_map)
    error_counts = (errors.loc[errors["error_type"].isin(["False positive", "False negative"])]
                    .groupby(["source_group", "error_type"]).size().unstack(fill_value=0))
    error_counts.to_csv(output_dir / "errors_by_source_group.csv")
    error_counts.plot(kind="bar", figsize=(8, 4.8), color=["#d68f42", "#b44a55"])
    plt.xlabel("Відкладена група джерела")
    plt.ylabel("Кількість помилок")
    plt.title("Хибні тривоги та пропуски за групою джерела")
    plt.xticks(rotation=25, ha="right")
    save("errors_by_source.png")

    # 9. Error analysis by confidence and class.
    errors["attack_probability"] = rf_prob
    errors["outcome"] = errors["error_type"].replace({"Correct": "Correct prediction"})
    plt.figure(figsize=(7.5, 4.8))
    sns.histplot(data=errors, x="attack_probability", hue="outcome", bins=25,
                 element="step", stat="density", common_norm=False, fill=False)
    plt.axvline(0.5, color="black", linestyle="--", linewidth=1, label="Поріг 0,5")
    plt.xlabel("Оцінка ймовірності атаки")
    plt.ylabel("Щільність")
    plt.title("Де помиляється модель: розподіл оцінок")
    save("errors_by_confidence.png")

    # 10. Per-error-type top feature shifts (log1p only for visualization).
    top_features = importances.tail(3)["feature"].tolist()
    categories = ["True negative", "False positive", "False negative", "True positive"]
    errors["outcome"] = np.select(
        [(errors["label"] == 0) & (errors["prediction"] == 0),
         (errors["label"] == 0) & (errors["prediction"] == 1),
         (errors["label"] == 1) & (errors["prediction"] == 0),
         (errors["label"] == 1) & (errors["prediction"] == 1)],
        categories,
        default="",
    )
    long = errors.melt(id_vars=["outcome"], value_vars=top_features, var_name="feature", value_name="value")
    long["log1p_value"] = np.log1p(long["value"].clip(lower=0))
    plt.figure(figsize=(8, 5))
    sns.boxplot(data=long, x="feature", y="log1p_value", hue="outcome", showfliers=False)
    plt.xlabel("Ознака (3 найважливіші для моделі)")
    plt.ylabel("log(1 + значення), лише для візуалізації")
    plt.title("Профілі ознак для різних типів результату")
    plt.legend(fontsize=7, ncol=2)
    save("errors_by_feature.png")

    return {"plots": paths, "shap_status": shap_status, "learning_curve": learning_rows}


def train(data_path: Path, output_dir: Path, model_dir: Path, image_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    data, data_info = load_clean_data(data_path)
    partitions = make_partitions(data)
    data_info.update(partitions.split_info)
    _save_json(output_dir / "data_summary.json", data_info)
    _save_json(output_dir / "split_summary.json", partitions.split_info)

    best_rf_params, _, tuning_rows, best_lr_params, _ = _search_hyperparameters(partitions)
    pd.DataFrame(tuning_rows).to_csv(output_dir / "hyperparameter_trials.csv", index=False)

    train_val_index = np.concatenate([partitions.train_index, partitions.validation_index])
    train_val = partitions.frame.iloc[train_val_index]
    test = partitions.test
    X_fit, y_fit = train_val[FEATURES], train_val["label"].to_numpy()
    X_test, y_test = test[FEATURES], test["label"].to_numpy()

    fitted: dict[str, Pipeline] = {}
    fit_seconds: dict[str, float] = {}
    for name, params in (("Logistic Regression", best_lr_params), ("Random Forest", best_rf_params)):
        model = pipeline_for(name, params)
        start = time.perf_counter()
        model.fit(X_fit, y_fit)
        fit_seconds[name] = float(time.perf_counter() - start)
        fitted[name] = model

    test_probabilities = {
        name: positive_probability(model, X_test)
        for name, model in fitted.items()
    }
    test_probabilities["Signature rules"] = _rule_probability(test)
    test_metrics = {
        name: metrics_for(y_test, probabilities)
        for name, probabilities in test_probabilities.items()
    }

    cv_frame = train_val
    cv_rows = {
        "Logistic Regression": _cross_validation("Logistic Regression", best_lr_params, cv_frame),
        "Random Forest": _cross_validation("Random Forest", best_rf_params, cv_frame),
        "Signature rules": _cross_validate_rules(cv_frame),
    }
    for rows in cv_rows.values():
        for row in rows:
            row["precision_attack"] = float(row["precision_attack"])
    pd.DataFrame([
        {"model": model_name, **fold_row}
        for model_name, rows in cv_rows.items()
        for fold_row in rows
    ]).to_csv(output_dir / "group_cv_metrics.csv", index=False)

    model_paths = {
        "Logistic Regression": model_dir / "logistic_regression_v2.joblib",
        "Random Forest": model_dir / "random_forest_v2.joblib",
    }
    model_sizes = {}
    model_hashes = {}
    latency_stats = {}
    for name, path in model_paths.items():
        joblib.dump(fitted[name], path, compress=3)
        artifact = path.read_bytes()
        model_sizes[name] = len(artifact)
        model_hashes[name] = "0x" + hashlib.sha256(artifact).hexdigest()
        latency_stats[name] = _latency_stats(fitted[name], X_test)

    comparison_rows = []
    for name in ("Signature rules", "Logistic Regression", "Random Forest"):
        folds = [row["f1_attack"] for row in cv_rows[name]]
        comparison_rows.append({
            "model": name,
            **{key: test_metrics[name][key] for key in (
                "accuracy", "precision_attack", "recall_attack", "f1_attack",
                "false_positive_rate", "false_negative_rate", "pr_auc", "roc_auc",
            )},
            "cv_f1_mean": float(np.mean(folds)),
            "cv_f1_sd": float(np.std(folds, ddof=1)),
            "fit_seconds": fit_seconds.get(name, 0.0),
            "prediction_latency_ms": latency_stats.get(name, {}).get("mean_ms", 0.0),
            "prediction_latency_p95_ms": latency_stats.get(name, {}).get("p95_ms", 0.0),
            "artifact_bytes": model_sizes.get(name, 0),
        })
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(output_dir / "model_comparison.csv", index=False)

    # Pseudonymize test sources in figures; raw IPs are not copied into result CSVs.
    errors = test[["label", "src_ip", *FEATURES]].copy()
    plot_results = _save_plots(image_dir, partitions, fitted, test_probabilities, test_metrics, cv_rows, tuning_rows, errors)

    demo_flows = make_demo_flows(partitions, model=fitted["Random Forest"])
    _save_json(output_dir / "demo_flows.json", demo_flows)
    # Store a private reference file for independent E2E assertion. The API never serves it.
    _save_json(output_dir / "demo_flow_truth.json", {
        sample["sample_id"]: sample["ground_truth"] for sample in demo_flows
    })
    public_demo_flows = [{key: value for key, value in sample.items() if key != "ground_truth"} for sample in demo_flows]
    _save_json(model_dir / "demo_flows.json", public_demo_flows)

    model_hash = model_hashes["Random Forest"]
    best_metrics = test_metrics["Random Forest"]
    model_card = {
        "model_name": "Random Forest IoT IDS",
        "model_version": settings.model_version,
        "task": "binary network-flow classification; 1=attack, 0=normal",
        "dataset": {
            "name": "ToN_IoT Network processed train/test CSV mirror",
            "source": "UNSW Canberra ToN_IoT project, academic-use mirror used in Lab 1",
            "input_rows": data_info["rows_loaded"],
            "rows_after_deduplication": data_info["rows_after_deduplication"],
            "features": FEATURES,
            "split": "StratifiedGroupKFold by src_ip: disjoint train, validation and held-out test groups",
            "seed": RANDOM_SEED,
        },
        "preprocessing": [
            "Remove exact duplicate rows",
            "Convert selected numeric features to numbers and represent invalid/nonfinite values as missing",
            "Median imputation fitted within each model training partition",
            "Do not use src_ip, dst_ip, label or type as model features",
            "Preserve extreme values; no clipping or scaling is used by Random Forest",
        ],
        "hyperparameters": best_rf_params,
        "decision_threshold": 0.5,
        "confidence_scale_bps": "probability(attack) multiplied by 10000; 5000 bps is contract threshold",
        "held_out_test_metrics": best_metrics,
        "group_cv_f1_mean": float(comparison.loc[comparison["model"] == "Random Forest", "cv_f1_mean"].iloc[0]),
        "group_cv_f1_sd": float(comparison.loc[comparison["model"] == "Random Forest", "cv_f1_sd"].iloc[0]),
        "artifact_file": model_paths["Random Forest"].name,
        "artifact_sha256": model_hash,
        "limitations": [
            "The data is a processed academic benchmark and does not represent all live IoT deployments.",
            "Group separation is by source IP because the CSV has no timestamp field.",
            "The model output is a statistical score, not proof that a physical device is compromised.",
            "Model threshold and performance require revalidation when the data source or feature schema changes.",
        ],
        "intended_use": "Educational analysis of simulated IoT network flows; the gateway policy and owner review remain responsible for enforcement.",
    }
    _save_json(model_dir / "model_card.json", model_card)

    summary = {
        "data": data_info,
        "best_hyperparameters": {"random_forest": best_rf_params, "logistic_regression": best_lr_params},
        "test_metrics": test_metrics,
        "cross_validation": cv_rows,
        "model_comparison": comparison_rows,
        "model_hashes": model_hashes,
        "model_sizes_bytes": model_sizes,
        "prediction_latency": latency_stats,
        "model_fit_seconds": fit_seconds,
        "shap_status": plot_results["shap_status"],
        "learning_curve": plot_results["learning_curve"],
        "plots": {name: Path(path).name for name, path in plot_results["plots"].items()},
    }
    _save_json(output_dir / "training_summary.json", summary)
    print(json.dumps(_json_value(summary), ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the IoT IDS models reproducibly.")
    parser.add_argument("--data", type=Path, default=settings.dataset_path)
    parser.add_argument("--output", type=Path, default=settings.code_root / "artifacts")
    parser.add_argument("--models", type=Path, default=settings.code_root / "models")
    parser.add_argument("--images", type=Path, default=settings.work_root / "images")
    args = parser.parse_args()
    train(args.data, args.output, args.models, args.images)


if __name__ == "__main__":
    main()
