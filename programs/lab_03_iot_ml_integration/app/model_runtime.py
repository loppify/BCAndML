"""Model loading, artifact verification and SHAP-based local explanations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.data_pipeline import FEATURES
from app.settings import settings


class ModelRuntime:
    def __init__(self, model_path: Path | None = None, card_path: Path | None = None):
        self.model_path = model_path or settings.model_path
        self.card_path = card_path or settings.model_card_path
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model artifact is missing: {self.model_path}. Run python -m app.train first.")
        if not self.card_path.is_file():
            raise FileNotFoundError(f"Model card is missing: {self.card_path}. Run python -m app.train first.")
        self.model_hash = "0x" + hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        self.card = json.loads(self.card_path.read_text(encoding="utf-8"))
        expected_hash = str(self.card.get("artifact_sha256", "")).lower()
        if expected_hash and expected_hash != self.model_hash.lower():
            raise ValueError("Random Forest artifact hash does not match its model card.")
        self.version = int(self.card.get("model_version", settings.model_version))
        self.model = joblib.load(self.model_path)
        classifier = self.model.named_steps["classifier"]
        if not hasattr(classifier, "feature_importances_"):
            raise TypeError("The primary IDS model must be a fitted tree ensemble.")
        self.classifier = classifier
        self._explainer = None

    def _feature_frame(self, features: dict[str, Any]) -> pd.DataFrame:
        if set(features) != set(FEATURES):
            missing = sorted(set(FEATURES) - set(features))
            extra = sorted(set(features) - set(FEATURES))
            raise ValueError(f"Feature schema mismatch. Missing={missing}; extra={extra}")
        values = {}
        for name in FEATURES:
            raw = features[name]
            if raw is None:
                values[name] = np.nan
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Feature {name} must be numeric or null.") from exc
            if not np.isfinite(number):
                raise ValueError(f"Feature {name} must be finite.")
            values[name] = number
        return pd.DataFrame([values], columns=FEATURES)

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        frame = self._feature_frame(features)
        classes = list(self.classifier.classes_)
        probability = float(self.model.predict_proba(frame)[0, classes.index(1)])
        confidence_bps = int(round(probability * 10_000))
        return {
            "is_attack": confidence_bps >= settings.confidence_threshold_bps,
            "confidence": probability,
            "confidence_bps": confidence_bps,
            "model_version": self.version,
            "artifact_hash": self.model_hash,
            "features": frame,
        }

    def explain(self, frame: pd.DataFrame, max_features: int = 5) -> list[dict[str, Any]]:
        transformed = self.model.named_steps["imputer"].transform(frame[FEATURES])
        try:
            import shap
            if self._explainer is None:
                self._explainer = shap.TreeExplainer(self.classifier)
            values = self._explainer.shap_values(transformed, check_additivity=False)
            if isinstance(values, list):
                contributions = np.asarray(values[1])[0]
            else:
                values = np.asarray(values)
                contributions = values[0, :, 1] if values.ndim == 3 else values[0]
            result = [
                {"feature": name, "value": None if pd.isna(frame.iloc[0][name]) else float(frame.iloc[0][name]),
                 "contribution": float(contributions[index]),
                 "direction": "підвищує оцінку атаки" if contributions[index] > 0 else "знижує оцінку атаки",
                 "method": "SHAP TreeExplainer"}
                for index, name in enumerate(FEATURES)
            ]
            return sorted(result, key=lambda item: abs(item["contribution"]), reverse=True)[:max_features]
        except Exception:
            # The trained artifact still exposes a deterministic local sensitivity fallback.
            base_probability = self.predict(frame.iloc[0].to_dict())["confidence"]
            median = self.model.named_steps["imputer"].statistics_
            result = []
            for index, name in enumerate(FEATURES):
                changed = frame.copy()
                changed.loc[changed.index[0], name] = median[index]
                probability = float(self.model.predict_proba(changed)[0, list(self.classifier.classes_).index(1)])
                contribution = base_probability - probability
                result.append({
                    "feature": name,
                    "value": None if pd.isna(frame.iloc[0][name]) else float(frame.iloc[0][name]),
                    "contribution": contribution,
                    "direction": "підвищує оцінку атаки" if contribution > 0 else "знижує оцінку атаки",
                    "method": "median perturbation sensitivity",
                })
            return sorted(result, key=lambda item: abs(item["contribution"]), reverse=True)[:max_features]

    def public_card(self) -> dict[str, Any]:
        return self.card
