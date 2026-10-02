"""
ML Engine — Predictive Maintenance Model

Predicts probability of vehicle breakdown within the next 7 days.
Uses historical Parquet data + PostgreSQL trip/alert/DTC history.

Pipeline:
  1. Feature engineering from historical telemetry
  2. Train baseline (Logistic Regression) and primary model (XGBoost)
  3. Evaluate against baseline with precision/recall/F1/AUC
  4. Serve predictions via FastAPI endpoint
  5. Batch score all 100K vehicles nightly
"""

import json
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Lazy imports for optional dependencies
try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        classification_report, roc_auc_score,
        precision_recall_fscore_support, confusion_matrix
    )
    from sklearn.pipeline import Pipeline
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "models"))
MODEL_DIR.mkdir(exist_ok=True)

# ── Feature Engineering ────────────────────────────────────────────────

# DTC severity weights (higher = more concerning)
DTC_SEVERITY = {
    "P0300": 9, "P0301": 9, "P0302": 9,  # misfire — high breakdown risk
    "P0700": 8, "C0035": 8,              # transmission, ABS
    "P0420": 6, "P0171": 5, "P0174": 5, # catalyst, lean
    "P0442": 4, "U0001": 7, "U0100": 7, # EVAP, CAN bus
}


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer features for predictive maintenance from historical telemetry.

    Input columns expected: vin, time (datetime), speed_kmh, soc_pct,
    odo_km, dtc (list), evt, has_fault, fuel_pct, battery_temp_c
    """
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])

    # Sort by VIN and time
    df = df.sort_values(["vin", "time"])

    features = []
    for vin, group in df.groupby("vin"):
        # ── Mileage features ─────────────────────────────────────────
        odo_max = group["odo_km"].max()
        odo_delta_30d = group["odo_km"].max() - group["odo_km"].min()

        # ── DTC features ─────────────────────────────────────────────
        all_dtcs = [d for dtcs in group["dtc"].dropna() for d in (dtcs if isinstance(dtcs, list) else [])]
        unique_dtcs = len(set(all_dtcs))
        dtc_count_30d = len(all_dtcs)
        max_dtc_severity = max((DTC_SEVERITY.get(d, 2) for d in all_dtcs), default=0)
        has_critical_dtc = int(any(d in {"P0300", "P0301", "P0302", "C0035"} for d in all_dtcs))

        # ── Harsh event features ──────────────────────────────────────
        harsh_count = group["evt"].notna().sum()
        harsh_rate = harsh_count / max(len(group), 1)
        brake_count = (group["evt"] == "HARSH_BRAKE").sum()

        # ── Speed features ────────────────────────────────────────────
        avg_speed = group["speed_kmh"].mean()
        max_speed = group["speed_kmh"].max()
        high_speed_pct = (group["speed_kmh"] > 90).mean()

        # ── Battery features (EV) ─────────────────────────────────────
        avg_soc = group["soc_pct"].mean() if "soc_pct" in group else np.nan
        min_soc = group["soc_pct"].min() if "soc_pct" in group else np.nan
        battery_temp_max = group["battery_temp_c"].max() if "battery_temp_c" in group else np.nan
        deep_discharge_events = (group["soc_pct"] < 10).sum() if "soc_pct" in group else 0

        # ── Idle / utilization ────────────────────────────────────────
        idle_pct = (group["speed_kmh"] < 2).mean()
        daily_km = odo_delta_30d / 30

        # ── Label: did this vehicle have a fault in next 7 days? ──────
        has_fault = int(group["has_fault"].any())

        features.append({
            "vin": vin,
            "odo_km": odo_max,
            "odo_delta_30d": odo_delta_30d,
            "daily_km": daily_km,
            "dtc_count_30d": dtc_count_30d,
            "unique_dtcs": unique_dtcs,
            "max_dtc_severity": max_dtc_severity,
            "has_critical_dtc": has_critical_dtc,
            "harsh_count": harsh_count,
            "harsh_rate": harsh_rate,
            "brake_count": brake_count,
            "avg_speed": avg_speed,
            "max_speed": max_speed,
            "high_speed_pct": high_speed_pct,
            "avg_soc": avg_soc if not np.isnan(avg_soc) else -1,
            "min_soc": min_soc if not np.isnan(min_soc) else -1,
            "battery_temp_max": battery_temp_max if not np.isnan(battery_temp_max) else -1,
            "deep_discharge_events": deep_discharge_events,
            "idle_pct": idle_pct,
            "label": has_fault,  # 1 = breakdown likely in 7 days
        })

    return pd.DataFrame(features)


FEATURE_COLS = [
    "odo_km", "odo_delta_30d", "daily_km",
    "dtc_count_30d", "unique_dtcs", "max_dtc_severity", "has_critical_dtc",
    "harsh_count", "harsh_rate", "brake_count",
    "avg_speed", "max_speed", "high_speed_pct",
    "avg_soc", "min_soc", "battery_temp_max", "deep_discharge_events",
    "idle_pct",
]


# ── Training ───────────────────────────────────────────────────────────

def train_and_evaluate(features_df: pd.DataFrame) -> Dict:
    """Train baseline + XGBoost models and return evaluation metrics."""
    if not HAS_SKLEARN:
        print("scikit-learn not available")
        return {}

    X = features_df[FEATURE_COLS].fillna(-1)
    y = features_df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    results = {}

    # ── Baseline: Logistic Regression ────────────────────────────────
    baseline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    baseline.fit(X_train, y_train)
    y_pred_base = baseline.predict(X_test)
    y_prob_base = baseline.predict_proba(X_test)[:, 1]

    prec, rec, f1, _ = precision_recall_fscore_support(y_test, y_pred_base, average="binary", zero_division=0)
    auc = roc_auc_score(y_test, y_prob_base) if len(y_test.unique()) > 1 else 0.5

    results["baseline"] = {
        "model": "LogisticRegression",
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "f1": round(float(f1), 4),
        "auc": round(float(auc), 4),
    }
    print(f"Baseline (LR): P={prec:.3f} R={rec:.3f} F1={f1:.3f} AUC={auc:.3f}")

    # Save baseline
    with open(MODEL_DIR / "baseline_model.pkl", "wb") as f:
        pickle.dump(baseline, f)

    # ── Primary: XGBoost ─────────────────────────────────────────────
    if HAS_XGB:
        scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            scale_pos_weight=scale_pos_weight,
            eval_metric="logloss",
            random_state=42,
            use_label_encoder=False,
            n_jobs=-1,
        )
        xgb_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )
        y_pred_xgb = xgb_model.predict(X_test)
        y_prob_xgb = xgb_model.predict_proba(X_test)[:, 1]

        prec, rec, f1, _ = precision_recall_fscore_support(y_test, y_pred_xgb, average="binary", zero_division=0)
        auc = roc_auc_score(y_test, y_prob_xgb) if len(y_test.unique()) > 1 else 0.5

        results["xgboost"] = {
            "model": "XGBoost",
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1": round(float(f1), 4),
            "auc": round(float(auc), 4),
            "feature_importance": dict(zip(FEATURE_COLS, xgb_model.feature_importances_.tolist())),
        }
        print(f"XGBoost:       P={prec:.3f} R={rec:.3f} F1={f1:.3f} AUC={auc:.3f}")

        # Save XGBoost model
        xgb_model.save_model(str(MODEL_DIR / "xgboost_model.json"))
        results["primary_model"] = "xgboost"
    else:
        results["primary_model"] = "baseline"

    # Save evaluation results
    with open(MODEL_DIR / "evaluation.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nModels saved to {MODEL_DIR}")
    return results


# ── Inference ──────────────────────────────────────────────────────────

class MaintenancePredictor:
    """Loads the trained model and scores individual vehicles."""

    def __init__(self):
        self._model = None
        self._model_type = None
        self._load_model()

    def _load_model(self):
        xgb_path = MODEL_DIR / "xgboost_model.json"
        baseline_path = MODEL_DIR / "baseline_model.pkl"

        if HAS_XGB and xgb_path.exists():
            self._model = xgb.XGBClassifier()
            self._model.load_model(str(xgb_path))
            self._model_type = "xgboost"
            print(f"Loaded XGBoost model from {xgb_path}")
        elif baseline_path.exists():
            with open(baseline_path, "rb") as f:
                self._model = pickle.load(f)
            self._model_type = "baseline"
            print(f"Loaded baseline model from {baseline_path}")
        else:
            print("No trained model found. Run training first.")

    def predict(self, features: Dict) -> Dict:
        """Predict breakdown probability for a single vehicle's features."""
        if self._model is None:
            return {"error": "no model loaded", "failure_prob_7d": 0.5}

        X = pd.DataFrame([features])[FEATURE_COLS].fillna(-1)
        prob = float(self._model.predict_proba(X)[0][1])
        label = prob >= 0.5

        confidence = "high" if prob > 0.75 or prob < 0.25 else "medium" if prob > 0.6 or prob < 0.4 else "low"

        return {
            "failure_prob_7d": round(prob, 4),
            "breakdown_likely": bool(label),
            "confidence": confidence,
            "model_version": self._model_type or "unknown",
            "recommended_action": _recommend_action(prob, features),
        }

    def batch_predict(self, features_list: List[Dict]) -> List[Dict]:
        """Predict for a batch of vehicles."""
        if self._model is None:
            return [{"error": "no model"} for _ in features_list]

        X = pd.DataFrame(features_list)[FEATURE_COLS].fillna(-1)
        probs = self._model.predict_proba(X)[:, 1]

        return [
            {
                "vin": f.get("vin"),
                "failure_prob_7d": round(float(p), 4),
                "breakdown_likely": bool(p >= 0.5),
                "confidence": "high" if p > 0.75 or p < 0.25 else "medium",
                "recommended_action": _recommend_action(float(p), f),
            }
            for f, p in zip(features_list, probs)
        ]


def _recommend_action(prob: float, features: Dict) -> str:
    """Generate a plain-language recommendation."""
    if prob >= 0.8:
        if features.get("has_critical_dtc"):
            return "URGENT: Critical fault codes detected. Remove vehicle from service immediately."
        return "HIGH RISK: Schedule maintenance inspection within 24 hours."
    if prob >= 0.6:
        if features.get("dtc_count_30d", 0) > 0:
            return "Schedule diagnostic scan and maintenance within 3 days."
        return "Monitor vehicle closely. Schedule preventive check within 7 days."
    if prob >= 0.4:
        return "Elevated risk. Consider preventive maintenance at next scheduled service."
    return "Low risk. Continue normal monitoring schedule."


# ── CLI ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import glob

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    train_p = sub.add_parser("train", help="Train models from Parquet data")
    train_p.add_argument("--data-dir", default="data/historical")
    train_p.add_argument("--days", type=int, default=30)

    score_p = sub.add_parser("score", help="Score a sample vehicle")
    args = parser.parse_args()

    if args.command == "train":
        print(f"Loading historical data from {args.data_dir}...")
        parquet_files = glob.glob(f"{args.data_dir}/**/*.parquet", recursive=True)
        print(f"Found {len(parquet_files)} Parquet files")

        if not parquet_files:
            print("No Parquet files found. Run historical_seeder.py first.")
        else:
            import pyarrow.parquet as pq
            dfs = [pq.read_table(f).to_pandas() for f in parquet_files[:args.days]]
            df = pd.concat(dfs, ignore_index=True)
            print(f"Loaded {len(df):,} events from {len(dfs)} files")

            print("Engineering features...")
            features_df = engineer_features(df)
            print(f"Feature matrix: {features_df.shape}")
            print(f"Label distribution:\n{features_df['label'].value_counts()}")

            print("Training models...")
            results = train_and_evaluate(features_df)
            print("\nEvaluation results:")
            print(json.dumps(results, indent=2))

    elif args.command == "score":
        predictor = MaintenancePredictor()
        sample = {col: np.random.rand() * 10 for col in FEATURE_COLS}
        sample["odo_km"] = 75000
        sample["dtc_count_30d"] = 3
        sample["has_critical_dtc"] = 1
        sample["vin"] = "DEMO_VIN"
        result = predictor.predict(sample)
        print(json.dumps(result, indent=2))
