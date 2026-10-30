---
name: classic-ml-architect
description: Architect-level classical machine learning — problem framing and label definition, tabular feature design, gradient-boosted trees versus neural nets, validation that respects time and groups, leakage, calibration, and the interpretability and monitoring a production model needs. Use when the task is prediction over structured data.
license: MIT
compatibility: XGBoost, LightGBM, scikit-learn, CatBoost
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/training-architect/classic-ml-architect
  crusor-origin: original
  crusor-sources: "scikit-learn.org/stable/user_guide; xgboost.readthedocs.io; developingwei.com/2020/03/05/awesome-decision-tree-papers"
  crusor-triggers: "classic ml, tabular model, xgboost, lightgbm, churn model, fraud model, feature engineering, label leakage, gradient boosting"
  crusor-verified-on: "2026-10-30"
---

# Classic ML Architect

For tabular prediction, **gradient-boosted trees still win**, and the hard part is
the label and the validation split — not the model.

## When to use

- Churn, fraud, credit, pricing, demand, propensity, ranking.
- Structured/tabular data with hundreds to millions of rows.
- A decision that needs an explainable score.

## When NOT to use

- Unstructured text/images/audio → neural approaches.
- A rules-based policy the business already trusts and can articulate.

## Decision 1 — Frame the problem

- State the decision the score drives, and the cost of each error type.
- Define the label precisely, with the prediction time: "churns within 30 days of
  observation date".
- Choose the metric from the cost structure: precision at a threshold for review
  queues, recall for safety, AUC/PR-AUC for ranking.
- Base rate matters: PR-AUC for rare events, never accuracy.

## Decision 2 — Validation

| Split | Use |
|---|---|
| random k-fold | only for i.i.d. data (rare) |
| time-based | anything with a time dimension |
| grouped (by user/account) | repeated observations of the same entity |
| nested/time-series CV | hyperparameter tuning without leakage |

- Leakage is the dominant failure: any feature that could not be known at
  prediction time must be excluded, including aggregates computed after the fact.
- Check for target-proxy features (an id that only exists after churn).
- Report performance on the most recent period, not the average across history.

## Decision 3 — Features

- Start with raw columns plus simple aggregates; trees find interactions themselves.
- Categorical: target/frequency encoding inside CV folds, or native categorical
  support.
- Time-window features must be computed as-of the observation time
  (`feature-store-architect`).
- Missingness is signal: keep an indicator column.
- Do not engineer hundreds of features before a baseline exists.

## Decision 4 — Model

| Data | Model |
|---|---|
| tabular, < millions of rows | LightGBM/XGBoost |
| tabular, high cardinality categoricals | CatBoost or target encoding |
| tiny data | logistic regression, regularised |
| ranking | LambdaMART / pair-wise objectives |
| need calibration | isotonic/Platt on a holdout |

- Tune a handful of parameters; the returns beyond that are noise on small data.
- Calibrate probabilities when the score feeds a decision or a price.

## Decision 5 — Explain and operate

- Feature importance (gain and SHAP) reviewed with domain experts — the model is a
  hypothesis, not an oracle.
- Fairness checks across cohorts before deployment, not after a complaint.
- Monitor input drift and prediction drift; labels arrive late, so also track
  proxies.
- Retrain on a schedule or on drift trigger, with the same eval gates.

## Failure modes at scale

- Random split on time-series data; near-perfect offline score, useless production.
- Label defined from a post-hoc table; leakage through a cancelled-account flag.
- Accuracy reported on a 1% base rate.
- Model retrained monthly but features computed with tomorrow's data.
- No calibration; scores used as probabilities in pricing.

## Verification receipts

1. Problem statement with label definition and decision cost.
2. Validation scheme diagram proving no leakage (time/group).
3. Baseline (rules or logistic) versus final model on the same split.
4. Calibration curve on a holdout period.
5. Feature-importance review signed off by a domain expert.
