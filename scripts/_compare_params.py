"""
Walk-forward comparison: v2 param configs vs v1 baseline.
Tries 4 configs, prints accuracy per year and overall.
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score
from loguru import logger
logger.remove(); logger.add(sys.stderr, level="WARNING")

from train_regime_xgb import (
    build_feature_matrix, get_labels, REGIME_ENCODE,
    _INITIAL_TRAIN_YEARS, _STEP_YEARS, NBER_EPISODES,
)
from flowmacro.data.store import read_features_v2

# ── Build combined feature matrix ────────────────────────────────────────────
print("Loading features...")
old_X  = build_feature_matrix()
new_df = read_features_v2(start="2010-01-01")
X_v2   = old_X.join(new_df, how="inner")
y      = get_labels()

print(f"v2 features: {X_v2.shape[1]} x {X_v2.shape[0]} weeks")
print(f"Labels     : {len(y)} rows\n")


# ── Walk-forward (reusable) ───────────────────────────────────────────────────
def walk_forward(X: pd.DataFrame, y: pd.Series, params: dict, start_labels: str) -> dict:
    y_enc = y.map(REGIME_ENCODE)
    data  = X.join(y_enc.rename("label"), how="inner").dropna(subset=["label"])
    thresh = X.shape[1] // 2 + 1
    data   = data.dropna(thresh=thresh + 1)   # need at least half features
    data   = data[data.index >= pd.Timestamp(start_labels)]

    years, accs = [], []
    train_start = data.index.min()
    train_end   = train_start + pd.DateOffset(years=_INITIAL_TRAIN_YEARS)

    while True:
        test_end = train_end + pd.DateOffset(years=_STEP_YEARS)
        train = data[data.index <  train_end]
        test  = data[(data.index >= train_end) & (data.index < test_end)]
        if len(train) < 40 or len(test) < 4:
            train_end = test_end
            if test_end > data.index.max():
                break
            continue
        tm = train.median()
        tr = train.fillna(tm);  te = test.fillna(tm)
        Xtr, ytr = tr.drop("label",axis=1), tr["label"]
        Xte, yte = te.drop("label",axis=1), te["label"]
        m = XGBClassifier(**params)
        m.fit(Xtr, ytr)
        acc = accuracy_score(yte, m.predict(Xte))
        years.append(train_end.year)
        accs.append(acc)
        train_end = test_end
        if test_end > data.index.max():
            break

    return {"years": years, "accs": accs, "overall": np.mean(accs)}


# ── Configs ───────────────────────────────────────────────────────────────────
BASE = dict(n_estimators=100, max_depth=4, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="mlogloss", random_state=42, verbosity=0)

configs = {
    "v1-baseline (17f, same params)": (
        old_X.join(y.map(REGIME_ENCODE).rename("label"), how="inner").drop("label",axis=1),
        {**BASE},
        "2010-01-01",
    ),
    "v2-current  (31f, same params)": (
        X_v2, {**BASE}, "2010-01-01",
    ),
    "v2-A  colsample=0.6 min_cw=3": (
        X_v2, {**BASE, "colsample_bytree": 0.6, "min_child_weight": 3}, "2010-01-01",
    ),
    "v2-B  colsample=0.5 min_cw=5 alpha=0.1": (
        X_v2, {**BASE, "colsample_bytree": 0.5, "min_child_weight": 5,
               "reg_alpha": 0.1, "reg_lambda": 2.0}, "2010-01-01",
    ),
    "v2-C  start 2013 (skip NaN warmup)": (
        X_v2, {**BASE, "colsample_bytree": 0.6, "min_child_weight": 3}, "2013-01-01",
    ),
}

# ── Run all configs ───────────────────────────────────────────────────────────
results = {}
for name, (X_cfg, params, start) in configs.items():
    print(f"Running: {name} ...")
    y_local = y if "label" not in X_cfg.columns else y
    res = walk_forward(X_cfg, y, params, start)
    results[name] = res
    print(f"  Overall: {res['overall']:.1%}")

# ── Print comparison table ────────────────────────────────────────────────────
all_years = sorted(set(yr for r in results.values() for yr in r["years"]))

header = f"{'Year':<6}" + "".join(f"{n[:20]:<22}" for n in results)
print("\n" + "=" * (6 + 22 * len(results)))
print(header)
print("=" * (6 + 22 * len(results)))

for yr in all_years:
    row = f"{yr:<6}"
    for name, res in results.items():
        if yr in res["years"]:
            i   = res["years"].index(yr)
            acc = res["accs"][i]
            row += f"{acc*100:5.1f}%               "
        else:
            row += f"{'—':<22}"
    print(row)

print("-" * (6 + 22 * len(results)))
overall_row = f"{'MEAN':<6}"
for name, res in results.items():
    overall_row += f"{res['overall']*100:5.1f}%               "
print(overall_row)
print("=" * (6 + 22 * len(results)))

# ── Best config ───────────────────────────────────────────────────────────────
best = max(results, key=lambda n: results[n]["overall"])
print(f"\nBest config : {best}")
print(f"Best OOS    : {results[best]['overall']:.1%}")
print(f"v1 baseline : {results['v1-baseline (17f, same params)']['overall']:.1%}")
diff = results[best]["overall"] - results["v1-baseline (17f, same params)"]["overall"]
print(f"Delta vs v1 : {diff:+.1%}")
