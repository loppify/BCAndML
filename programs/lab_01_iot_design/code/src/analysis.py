from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from download_data import download


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw" / "ton_iot_network.csv"
IMAGES = ROOT.parent / "images"
ARTIFACTS = ROOT.parent / "artifacts"
SEED = 42
FEATURES = [
    "src_port", "dst_port", "duration", "src_bytes", "dst_bytes",
    "missed_bytes", "src_pkts", "src_ip_bytes", "dst_pkts", "dst_ip_bytes",
    "dns_qclass", "dns_qtype", "dns_rcode", "http_request_body_len",
    "http_response_body_len", "http_status_code",
]


def _style() -> None:
    sns.set_theme(style="whitegrid", context="notebook", font_scale=0.9)
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.dpi"] = 180


def _save(fig: plt.Figure, name: str) -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(IMAGES / name, bbox_inches="tight")
    plt.close(fig)


def _metric_row(y_true: pd.Series, pred: np.ndarray, score: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision_attack": float(precision_score(y_true, pred, zero_division=0)),
        "recall_attack": float(recall_score(y_true, pred, zero_division=0)),
        "f1_attack": float(f1_score(y_true, pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, score)),
        "roc_auc": float(roc_auc_score(y_true, score)),
    }


def run() -> dict:
    _style()
    if not DATA.exists():
        download()

    data = pd.read_csv(DATA, low_memory=False)
    required = set(FEATURES + ["label", "type", "src_ip", "dst_ip", "conn_state"])
    missing_columns = sorted(required - set(data.columns))
    if missing_columns:
        raise ValueError(f"Dataset schema changed, missing columns: {missing_columns}")

    original_rows = len(data)
    duplicate_rows = int(data.duplicated().sum())
    data = data.drop_duplicates().reset_index(drop=True)
    data["label"] = data["label"].astype(int)
    data["type"] = data["type"].astype(str)

    # 1. Binary class balance.
    fig, ax = plt.subplots(figsize=(7, 4))
    counts = data["label"].map({0: "Нормальний трафік", 1: "Атака"}).value_counts()
    sns.barplot(x=counts.index, y=counts.values, hue=counts.index, palette=["#4c956c", "#d1495b"], legend=False, ax=ax)
    ax.set(title="Розподіл бінарної цільової ознаки", xlabel="Клас", ylabel="Кількість потоків")
    for container in ax.containers:
        ax.bar_label(container, fmt="%.0f")
    _save(fig, "class_distribution.png")

    # 2. Attack family counts.
    attack_counts = data.loc[data.label == 1, "type"].value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    attack_counts.plot.barh(color="#d1495b", ax=ax)
    ax.set(title="Кількість записів за типом атаки", xlabel="Кількість потоків", ylabel="Тип атаки")
    _save(fig, "attack_types.png")

    # 3. Source endpoint identity vs class, used for grouped validation only.
    source_table = pd.crosstab(data.src_ip, data.label).rename(columns={0: "Нормальний", 1: "Атака"})
    source_table["total"] = source_table.sum(axis=1)
    top_sources = source_table.nlargest(15, "total").drop(columns="total")
    fig, ax = plt.subplots(figsize=(9, 6))
    top_sources.plot.barh(stacked=True, color=["#4c956c", "#d1495b"], ax=ax)
    ax.set(title="Класи за адресою джерела для 15 найчастіших вузлів", xlabel="Кількість потоків", ylabel="src_ip")
    ax.invert_yaxis()
    _save(fig, "source_ip_grouping.png")

    # 4. Heavy-tailed numeric features, shown on log scale.
    plot_features = ["duration", "src_bytes", "dst_bytes", "src_pkts", "dst_pkts"]
    sample = data.sample(n=min(30_000, len(data)), random_state=SEED)
    fig, axes = plt.subplots(1, len(plot_features), figsize=(15, 4))
    for ax, feature in zip(axes, plot_features, strict=True):
        vals = np.log1p(sample[feature].clip(lower=0))
        sns.histplot(vals, bins=45, color="#386cb0", ax=ax)
        ax.set(title=feature, xlabel="ln(1 + значення)", ylabel="Частота")
    fig.suptitle("Розподіли ключових числових ознак після log1p")
    _save(fig, "numeric_distributions.png")

    # 5. Missing and exact duplicate records.
    miss = data.isna().sum().sort_values(ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].bar(["Пропущені значення"], [int(miss.sum())], color="#386cb0")
    axes[0].set(title="Повнота ознак", ylabel="Кількість пропусків")
    axes[0].text(0, 0, f"{int(miss.sum())} пропусків", ha="center", va="bottom")
    axes[1].bar(["Унікальні", "Точні дублікати"], [len(data), duplicate_rows], color=["#4c956c", "#e09f3e"])
    axes[1].set(title="Перевірка повторів до очищення", ylabel="Кількість рядків")
    _save(fig, "missing_duplicates.png")

    # 6. Correlation matrix of the selected numeric features.
    corr_features = ["duration", "src_bytes", "dst_bytes", "missed_bytes", "src_pkts", "src_ip_bytes", "dst_pkts", "dst_ip_bytes", "dst_port", "http_status_code"]
    corr = data[corr_features].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(corr, cmap="vlag", center=0, vmin=-1, vmax=1, square=True, ax=ax)
    ax.set(title="Кореляції Спірмена між числовими мережевими ознаками")
    _save(fig, "correlation_matrix.png")

    # 7. Outliers shown on a logarithmic scale, separated by class.
    outlier_features = ["duration", "src_bytes", "dst_bytes", "src_pkts"]
    sample = data.sample(n=min(20_000, len(data)), random_state=SEED)
    melted = sample[["label", *outlier_features]].copy()
    for feature in outlier_features:
        melted[feature] = np.log1p(melted[feature].clip(lower=0))
    long = melted.melt(id_vars="label", var_name="Ознака", value_name="ln(1 + значення)")
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.boxplot(data=long, x="Ознака", y="ln(1 + значення)", hue="label", showfliers=False, palette={0: "#4c956c", 1: "#d1495b"}, ax=ax)
    ax.set(title="Викиди та розкид ознак за класами", xlabel="Ознака", ylabel="ln(1 + значення)")
    ax.legend(title="Мітка", labels=["Нормальний", "Атака"])
    _save(fig, "outlier_boxplots.png")

    # Group validation by source endpoint: no source IP occurs in both partitions.
    model_data = data.dropna(subset=["label", "src_ip"]).copy()
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    folds = list(splitter.split(model_data[FEATURES], model_data.label, groups=model_data.src_ip))
    train_idx, test_idx = folds[4]
    train, test = model_data.iloc[train_idx], model_data.iloc[test_idx]
    X_train, y_train = train[FEATURES], train.label
    X_test, y_test = test[FEATURES], test.label

    # Rule baseline: known management ports or a high-rate source with failed/initial state.
    rules = (
        test.dst_port.isin([23, 2323, 3389, 7547])
        | (test.conn_state.isin(["S0", "REJ"]) & (test.src_pkts >= 100))
    ).astype(int).to_numpy()
    results: dict[str, dict[str, float]] = {"Signature rules": _metric_row(y_test, rules, rules.astype(float))}

    logistic = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(max_iter=400, class_weight="balanced", random_state=SEED),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logistic.fit(X_train, y_train)
    lr_scores = logistic.predict_proba(X_test)[:, 1]
    lr_pred = (lr_scores >= 0.5).astype(int)
    results["Logistic regression"] = _metric_row(y_test, lr_pred, lr_scores)

    forest = make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestClassifier(
            n_estimators=100,
            max_depth=18,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=SEED,
        ),
    )
    forest.fit(X_train, y_train)
    rf_scores = forest.predict_proba(X_test)[:, 1]
    rf_pred = (rf_scores >= 0.5).astype(int)
    results["Random Forest"] = _metric_row(y_test, rf_pred, rf_scores)

    benign_train = train.loc[train.label == 0, FEATURES]
    anomaly = make_pipeline(
        SimpleImputer(strategy="median"),
        IsolationForest(n_estimators=100, contamination=0.05, max_samples=512, n_jobs=-1, random_state=SEED),
    )
    anomaly.fit(benign_train)
    iforest = anomaly[-1]
    anomaly_scores = -iforest.decision_function(anomaly[0].transform(X_test))
    anomaly_pred = (iforest.predict(anomaly[0].transform(X_test)) == -1).astype(int)
    results["Isolation Forest"] = _metric_row(y_test, anomaly_pred, anomaly_scores)

    fig, ax = plt.subplots(figsize=(9, 5))
    metric_frame = pd.DataFrame(results).T[["precision_attack", "recall_attack", "f1_attack"]]
    metric_frame.plot.bar(ax=ax, color=["#4c956c", "#d1495b", "#386cb0"])
    ax.set(title="Порівняння правил і моделей на груповій відкладеній вибірці", ylabel="Значення метрики", xlabel="Метод", ylim=(0, 1.05))
    ax.legend(["Precision атаки", "Recall атаки", "F1 атаки"], loc="lower right")
    ax.tick_params(axis="x", rotation=15)
    _save(fig, "model_comparison.png")

    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(confusion_matrix(y_test, rf_pred), annot=True, fmt="d", cmap="Blues", cbar=False, ax=ax)
    ax.set(title="Матриця помилок Random Forest", xlabel="Передбачений клас", ylabel="Фактичний клас", xticklabels=["Нормальний", "Атака"], yticklabels=["Нормальний", "Атака"])
    _save(fig, "rf_confusion_matrix.png")

    rf_model = forest[-1]
    importance = pd.Series(rf_model.feature_importances_, index=FEATURES).sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(8, 6))
    importance.sort_values().plot.barh(color="#386cb0", ax=ax)
    ax.set(title="Важливість ознак у Random Forest", xlabel="Важливість Gini", ylabel="Ознака")
    _save(fig, "feature_importance.png")

    summary = {
        "source": "ToN_IoT Network processed train/test CSV mirror",
        "source_url": "https://research.unsw.edu.au/projects/toniot-datasets",
        "mirror_url": "https://huggingface.co/datasets/codymlewis/TON_IoT_network",
        "dataset_path": str(DATA.relative_to(ROOT)),
        "rows_loaded": int(original_rows),
        "columns": int(data.shape[1]),
        "features_excluding_labels": int(data.shape[1] - 2),
        "rows_after_exact_deduplication": int(len(data)),
        "exact_duplicates_removed": duplicate_rows,
        "missing_values": int(data.isna().sum().sum()),
        "label_counts": {str(k): int(v) for k, v in data.label.value_counts().sort_index().items()},
        "type_counts": {str(k): int(v) for k, v in data.type.value_counts().sort_index().items()},
        "unique_source_ips": int(data.src_ip.nunique()),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_source_ips": int(train.src_ip.nunique()),
        "test_source_ips": int(test.src_ip.nunique()),
        "group_overlap": int(len(set(train.src_ip) & set(test.src_ip))),
        "train_label_counts": {str(k): int(v) for k, v in y_train.value_counts().sort_index().items()},
        "test_label_counts": {str(k): int(v) for k, v in y_test.value_counts().sort_index().items()},
        "features": FEATURES,
        "random_seed": SEED,
        "metrics": results,
        "top_random_forest_features": {str(k): float(v) for k, v in importance.head(10).items()},
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "analysis_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(results).T.to_csv(ARTIFACTS / "initial_model_metrics.csv", index_label="model")
    importance.rename("importance").to_csv(ARTIFACTS / "feature_importance.csv", index_label="feature")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run()
