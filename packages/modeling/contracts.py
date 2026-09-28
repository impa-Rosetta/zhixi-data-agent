"""Provider-independent, bounded model jobs. These contracts do not grant authority."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

MAX_MODEL_BYTES = 20 * 1024 * 1024
MAX_ROWS = 20_000
MAX_FEATURES = 50
FieldName = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Cell = Annotated[StrictStr, Field(max_length=2000)] | StrictInt | StrictFloat | None
Algorithm = Literal[
    "linear_regression",
    "decision_tree",
    "random_forest",
    "logistic_regression",
    "kmeans",
    "isolation_forest",
]
Task = Literal["regression", "classification", "clustering", "anomaly_detection"]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class _LinearParameters(_StrictContract):
    pass


class _TreeParameters(_StrictContract):
    max_depth: StrictInt = Field(default=6, ge=1, le=20)
    min_samples_leaf: StrictInt = Field(default=2, ge=1, le=100)


class _ForestParameters(_TreeParameters):
    n_estimators: StrictInt = Field(default=100, ge=10, le=500)


class _LogisticParameters(_StrictContract):
    C: StrictFloat = Field(default=1.0, gt=0, le=100)
    max_iter: StrictInt = Field(default=500, ge=100, le=2000)


class _KMeansParameters(_StrictContract):
    n_clusters: StrictInt = Field(default=3, ge=2, le=10)
    max_iter: StrictInt = Field(default=300, ge=100, le=1000)


class _IsolationParameters(_StrictContract):
    n_estimators: StrictInt = Field(default=100, ge=10, le=500)
    contamination: StrictFloat = Field(default=0.1, gt=0, le=0.5)


_PARAMETERS: dict[str, type[_StrictContract]] = {
    "linear_regression": _LinearParameters,
    "decision_tree": _TreeParameters,
    "random_forest": _ForestParameters,
    "logistic_regression": _LogisticParameters,
    "kmeans": _KMeansParameters,
    "isolation_forest": _IsolationParameters,
}
_TASKS: dict[str, set[str]] = {
    "linear_regression": {"regression"},
    "decision_tree": {"regression", "classification"},
    "random_forest": {"regression", "classification"},
    "logistic_regression": {"classification"},
    "kmeans": {"clustering"},
    "isolation_forest": {"anomaly_detection"},
}


class ModelSpec(_StrictContract):
    version: Literal[1] = 1
    algorithm: Algorithm
    task: Task
    source_artifact_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    source_digest: Digest
    features: tuple[FieldName, ...] = Field(min_length=1, max_length=MAX_FEATURES)
    target: FieldName | None = None
    split: Literal["random", "time", "group"] = "random"
    time_field: FieldName | None = None
    group_field: FieldName | None = None
    intended_use: Literal["current_patterns", "future_prediction"] = "current_patterns"
    random_seed: StrictInt = Field(default=42, ge=0, le=2**32 - 1)
    validation_fraction: StrictFloat = Field(default=0.2, ge=0.1, le=0.4)
    parameters: dict[str, StrictInt | StrictFloat | StrictStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        if self.task not in _TASKS[self.algorithm]:
            raise ValueError("model.algorithm_task_mismatch")
        fields = (*self.features, self.target, self.time_field, self.group_field)
        if any(name is not None and not name.strip() for name in fields):
            raise ValueError("model.empty_field")
        if len(set(self.features)) != len(self.features):
            raise ValueError("model.duplicate_feature")
        supervised = self.task in {"regression", "classification"}
        if supervised != (self.target is not None):
            raise ValueError("model.target_required_only_for_supervised_tasks")
        metadata = [name for name in (self.target, self.time_field, self.group_field) if name]
        if len(set(metadata)) != len(metadata) or set(metadata).intersection(self.features):
            raise ValueError("model.leaking_split_or_target_field")
        if self.split == "random" and (self.time_field is not None or self.group_field is not None):
            raise ValueError("model.random_split_metadata_forbidden")
        if self.split == "time" and (self.time_field is None or self.group_field is not None):
            raise ValueError("model.time_split_requires_time_field")
        if self.split == "group" and (self.group_field is None or self.time_field is not None):
            raise ValueError("model.group_split_requires_group_field")
        if self.intended_use == "future_prediction" and self.split != "time":
            raise ValueError("model.future_prediction_requires_time_split")
        # Validation only: no imports, estimator construction, SQL, file access or training.
        _PARAMETERS[self.algorithm].model_validate(self.parameters)
        return self

    def effective_parameters(self) -> dict[str, object]:
        """Expose explicit code-owned defaults for confirmations and immutable job manifests."""
        return dict(_PARAMETERS[self.algorithm].model_validate(self.parameters).model_dump())


class ModelFileManifest(_StrictContract):
    format: Literal["skops"] = "skops"
    content_digest: Digest
    size_bytes: StrictInt = Field(ge=1, le=MAX_MODEL_BYTES)
    dependencies: dict[StrictStr, StrictStr]

    @model_validator(mode="after")
    def fixed_dependencies(self) -> Self:
        if set(self.dependencies) != {"scikit-learn", "skops", "numpy", "scipy"}:
            raise ValueError("model.dependency_set_mismatch")
        if any(
            re.fullmatch(r"\d+\.\d+\.\d+", value) is None for value in self.dependencies.values()
        ):
            raise ValueError("model.exact_dependency_versions_required")
        return self


class PredictionRequest(_StrictContract):
    model_version_id: uuid.UUID
    rows: list[dict[FieldName, Cell]] = Field(min_length=1, max_length=MAX_ROWS)

    @model_validator(mode="after")
    def bounded_rows(self) -> Self:
        keys = set(self.rows[0])
        if not keys or len(keys) > MAX_FEATURES or any(not key.strip() for key in keys):
            raise ValueError("model.invalid_feature_names")
        if any(set(row) != keys for row in self.rows):
            raise ValueError("model.inconsistent_prediction_fields")
        if len(self.model_dump_json().encode("utf-8")) > MAX_MODEL_BYTES:
            raise ValueError("model.input_too_large")
        return self

    def validate_features(self, features: tuple[str, ...]) -> None:
        """Called against the authorized model version, never a client-declared schema."""
        if (
            not features
            or len(set(features)) != len(features)
            or set(self.rows[0]) != set(features)
        ):
            raise ValueError("model.feature_mismatch")


MetricName = Literal[
    "mae",
    "rmse",
    "r2",
    "precision_macro",
    "recall_macro",
    "f1_macro",
    "roc_auc",
    "silhouette",
    "anomaly_fraction",
]
_REQUIRED_METRICS: dict[str, set[str]] = {
    "regression": {"mae", "rmse", "r2"},
    "classification": {"precision_macro", "recall_macro", "f1_macro"},
    "clustering": {"silhouette"},
    "anomaly_detection": {"anomaly_fraction"},
}


class EvaluationMetric(_StrictContract):
    name: MetricName
    value: StrictFloat | None
    unavailable_reason: Annotated[StrictStr, Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def honest_metric(self) -> Self:
        if (self.value is None) != (self.unavailable_reason is not None):
            raise ValueError("model.undefined_metric_requires_reason")
        if self.unavailable_reason is not None and not self.unavailable_reason.strip():
            raise ValueError("model.empty_metric_reason")
        if self.value is not None:
            if self.name in {"mae", "rmse"} and self.value < 0:
                raise ValueError("model.invalid_error_metric")
            if self.name == "r2" and self.value > 1:
                raise ValueError("model.invalid_r2")
            if self.name == "silhouette" and not -1 <= self.value <= 1:
                raise ValueError("model.invalid_silhouette")
            if self.name not in {"mae", "rmse", "r2", "silhouette"} and not 0 <= self.value <= 1:
                raise ValueError("model.invalid_fraction_metric")
        return self


class ModelTrainingResult(_StrictContract):
    """Future executor output; successful schema validation is not proof of execution."""

    version: Literal[1] = 1
    spec: ModelSpec
    model_file: ModelFileManifest
    total_count: StrictInt = Field(ge=1, le=MAX_ROWS)
    sample_count: StrictInt = Field(ge=1, le=MAX_ROWS)
    dropped_count: StrictInt = Field(ge=0, le=MAX_ROWS)
    train_count: StrictInt = Field(ge=1, le=MAX_ROWS)
    validation_count: StrictInt = Field(ge=0, le=MAX_ROWS)
    metrics: tuple[EvaluationMetric, ...] = Field(min_length=1, max_length=9)
    baseline_metrics: tuple[EvaluationMetric, ...] = Field(default=(), max_length=9)
    warnings: tuple[Annotated[StrictStr, Field(min_length=1, max_length=500)], ...] = Field(
        min_length=1,
        max_length=10,
    )

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        supervised = self.spec.task in {"regression", "classification"}
        if self.sample_count < (30 if supervised else 20):
            raise ValueError("model.insufficient_samples")
        if self.sample_count + self.dropped_count != self.total_count:
            raise ValueError("model.sample_count_mismatch")
        if self.train_count + self.validation_count != self.sample_count:
            raise ValueError("model.split_count_mismatch")
        if supervised and self.validation_count < 2:
            raise ValueError("model.validation_samples_required")
        if not supervised and self.validation_count != 0:
            raise ValueError("model.unsupervised_holdout_not_supported")
        if self.spec.task == "clustering":
            clusters = self.spec.effective_parameters()["n_clusters"]
            assert isinstance(clusters, int)
            if self.sample_count <= clusters:
                raise ValueError("model.clusters_require_more_samples")
        required = _REQUIRED_METRICS[self.spec.task]
        allowed = required | ({"roc_auc"} if self.spec.task == "classification" else set())
        for records in (self.metrics, self.baseline_metrics):
            names = [item.name for item in records]
            if len(names) != len(set(names)) or not set(names).issubset(allowed):
                raise ValueError("model.unexpected_metrics")
        if not required.issubset({item.name for item in self.metrics}):
            raise ValueError("model.required_metrics_missing")
        baseline = {item.name for item in self.baseline_metrics}
        if supervised and not required.issubset(baseline):
            raise ValueError("model.baseline_required")
        if not supervised and baseline:
            raise ValueError("model.unsupervised_baseline_not_supported")
        if any(not warning.strip() for warning in self.warnings):
            raise ValueError("model.empty_warning")
        return self
