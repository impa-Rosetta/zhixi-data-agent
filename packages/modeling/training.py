"""Fixed-estimator training, intended only for the isolated modeling executor.

Not imported by API routes or Celery tasks. No SQL, networking or dynamic imports.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version
from typing import Any

import numpy as np
import skops.io as sio  # type: ignore[import-untyped]
from sklearn.cluster import KMeans  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.dummy import DummyClassifier, DummyRegressor  # type: ignore[import-untyped]
from sklearn.ensemble import (  # type: ignore[import-untyped]
    IsolationForest,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import (  # type: ignore[import-untyped]
    LinearRegression,
    LogisticRegression,
)
from sklearn.metrics import (  # type: ignore[import-untyped]
    confusion_matrix,
    mean_absolute_error,
    precision_recall_fscore_support,
    r2_score,
    root_mean_squared_error,
    silhouette_score,
)
from sklearn.model_selection import (  # type: ignore[import-untyped]
    GroupShuffleSplit,
    train_test_split,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]
from sklearn.tree import (  # type: ignore[import-untyped]
    DecisionTreeClassifier,
    DecisionTreeRegressor,
)

from packages.modeling.contracts import EvaluationMetric, ModelFileManifest, ModelTrainingResult
from packages.modeling.data import ModelDataError, PreparedTrainingData


@dataclass(frozen=True)
class TrainingOutput:
    result: ModelTrainingResult
    model_bytes: bytes
    pipeline: Any
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    validation_predictions: tuple[object, ...]
    explanation: dict[str, object]


def _split(data: PreparedTrainingData) -> tuple[list[int], list[int]]:
    spec = data.spec
    indices = list(range(len(data.rows)))
    if spec.target is None:
        return indices, []
    y = [row[data.columns.index(spec.target)] for row in data.rows]
    try:
        if spec.split == "time":
            assert spec.time_field is not None
            column = data.columns.index(spec.time_field)
            times = []
            for row in data.rows:
                value = row[column]
                if not isinstance(value, str):
                    raise ModelDataError("model.invalid_time_field")
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ModelDataError("model.timezone_required")
                times.append(parsed.timestamp())
            ordered = sorted(indices, key=lambda i: times[i])
            cutoff = len(indices) - math.ceil(len(indices) * spec.validation_fraction)
            # Keep equal timestamps on the validation side, avoiding boundary leakage.
            boundary = times[ordered[cutoff]]
            train = [i for i in ordered if times[i] < boundary]
            validation = [i for i in ordered if times[i] >= boundary]
        elif spec.split == "group":
            assert spec.group_field is not None
            groups = [row[data.columns.index(spec.group_field)] for row in data.rows]
            a, b = next(
                GroupShuffleSplit(
                    n_splits=1, test_size=spec.validation_fraction, random_state=spec.random_seed
                ).split(indices, y, groups)
            )
            train, validation = a.tolist(), b.tolist()
        else:
            train, validation = train_test_split(
                indices,
                test_size=spec.validation_fraction,
                random_state=spec.random_seed,
                stratify=y if spec.task == "classification" else None,
            )
    except ModelDataError:
        raise
    except (ValueError, IndexError) as exc:
        raise ModelDataError("model.invalid_split") from exc
    if len(train) < 2 or len(validation) < 2:
        raise ModelDataError("model.insufficient_split_samples")
    if spec.task == "classification":
        required = set(y)
        if {y[i] for i in train} != required or {y[i] for i in validation} != required:
            raise ModelDataError("model.split_missing_class")
    return train, validation


def _metrics(task: str, actual: Any, predicted: Any) -> tuple[EvaluationMetric, ...]:
    if task == "regression":
        result = [
            EvaluationMetric(name="mae", value=float(mean_absolute_error(actual, predicted))),
            EvaluationMetric(name="rmse", value=float(root_mean_squared_error(actual, predicted))),
        ]
        if len(set(actual)) == 1:
            result.append(
                EvaluationMetric(
                    name="r2", value=None, unavailable_reason="constant_validation_target"
                )
            )
        else:
            result.append(EvaluationMetric(name="r2", value=float(r2_score(actual, predicted))))
        return tuple(result)
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual, predicted, average="macro", zero_division=0
    )
    return (
        EvaluationMetric(name="precision_macro", value=float(precision)),
        EvaluationMetric(name="recall_macro", value=float(recall)),
        EvaluationMetric(name="f1_macro", value=float(f1)),
    )


def train_model(data: PreparedTrainingData) -> TrainingOutput:
    spec = data.spec
    train, validation = _split(data)
    feature_count = len(spec.features)
    x = np.array(
        [
            [np.nan if value is None else value for value in row[:feature_count]]
            for row in data.rows
        ],
        dtype=object,
    )
    numeric = [i for i, name in enumerate(spec.features) if data.feature_types[name] == "numeric"]
    categorical = [i for i in range(feature_count) if i not in numeric]
    transformers = []
    if numeric:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        (
                            "impute",
                            SimpleImputer(strategy="most_frequent", keep_empty_features=True),
                        ),
                        (
                            "encode",
                            OneHotEncoder(
                                handle_unknown="ignore", max_categories=64, sparse_output=False
                            ),
                        ),
                    ]
                ),
                categorical,
            )
        )
    preprocess = ColumnTransformer(transformers, sparse_threshold=0)
    parameters = spec.effective_parameters()
    classification = spec.task == "classification"
    constructors: dict[str, Any] = {
        "linear_regression": LinearRegression,
        "decision_tree": DecisionTreeClassifier if classification else DecisionTreeRegressor,
        "random_forest": RandomForestClassifier if classification else RandomForestRegressor,
        "logistic_regression": LogisticRegression,
        "kmeans": KMeans,
        "isolation_forest": IsolationForest,
    }
    if spec.algorithm != "linear_regression":
        parameters["random_state"] = spec.random_seed
    if spec.algorithm in {"random_forest", "isolation_forest"}:
        parameters["n_jobs"] = 1
    if spec.algorithm == "kmeans":
        parameters["n_init"] = 10
    pipeline = Pipeline(
        [("prepare", preprocess), ("model", constructors[spec.algorithm](**parameters))]
    )
    explanation: dict[str, object] = {"feature_names": list(spec.features)}
    predictions: tuple[object, ...] = ()
    baseline_metrics: tuple[EvaluationMetric, ...] = ()
    if spec.target is not None:
        target_column = data.columns.index(spec.target)
        y = np.array(
            [row[target_column] for row in data.rows], dtype=None if classification else float
        )
        pipeline.fit(x[train], y[train])
        prediction = pipeline.predict(x[validation])
        predictions = tuple(prediction.tolist())
        metrics = _metrics(spec.task, y[validation], prediction)
        baseline = (
            DummyClassifier(strategy="most_frequent")
            if classification
            else DummyRegressor(strategy="mean")
        )
        baseline.fit(x[train], y[train])
        baseline_metrics = _metrics(spec.task, y[validation], baseline.predict(x[validation]))
        explanation["validation_actual"] = y[validation].tolist()
        if classification:
            labels = pipeline.named_steps["model"].classes_.tolist()
            explanation["classes"] = labels
            explanation["confusion_matrix"] = confusion_matrix(
                y[validation], prediction, labels=labels
            ).tolist()
    else:
        pipeline.fit(x)
        labels = pipeline.predict(x)
        if spec.task == "clustering":
            transformed = preprocess.transform(x)
            if 1 < len(set(labels)) < len(x):
                metric = EvaluationMetric(
                    name="silhouette",
                    value=float(
                        silhouette_score(
                            transformed,
                            labels,
                            sample_size=min(2000, len(x)),
                            random_state=spec.random_seed,
                        )
                    ),
                )
            else:
                metric = EvaluationMetric(
                    name="silhouette",
                    value=None,
                    unavailable_reason="insufficient_distinct_clusters",
                )
            metrics = (metric,)
            explanation["cluster_centers"] = pipeline.named_steps["model"].cluster_centers_.tolist()
            explanation["cluster_sizes"] = {
                str(label): int(sum(labels == label)) for label in sorted(set(labels))
            }
        else:
            metrics = (
                EvaluationMetric(
                    name="anomaly_fraction", value=float(sum(labels == -1) / len(labels))
                ),
            )
            explanation["anomaly_scores"] = pipeline.decision_function(x).tolist()
            explanation["labels"] = labels.tolist()
    estimator = pipeline.named_steps["model"]
    explanation["transformed_features"] = preprocess.get_feature_names_out().tolist()
    if hasattr(estimator, "feature_importances_"):
        explanation["feature_importances"] = estimator.feature_importances_.tolist()
    if hasattr(estimator, "coef_"):
        explanation["coefficients"] = estimator.coef_.tolist()
    model_bytes: bytes = sio.dumps(pipeline)
    manifest = ModelFileManifest(
        content_digest=hashlib.sha256(model_bytes).hexdigest(),
        size_bytes=len(model_bytes),
        dependencies={name: version(name) for name in ("scikit-learn", "skops", "numpy", "scipy")},
    )
    result = ModelTrainingResult(
        spec=spec,
        model_file=manifest,
        total_count=data.total_count,
        sample_count=len(data.rows),
        dropped_count=data.dropped_count,
        train_count=len(train),
        validation_count=len(validation),
        metrics=metrics,
        baseline_metrics=baseline_metrics,
        warnings=("模型反映样本关联，不证明因果；无人工标签的异常结果没有准确率。",),
    )
    return TrainingOutput(
        result, model_bytes, pipeline, tuple(train), tuple(validation), predictions, explanation
    )
