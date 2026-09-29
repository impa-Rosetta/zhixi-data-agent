"""Internal model inference for the isolated executor, not a model-upload API.

The caller must authorize the stored version before supplying its bytes/metadata.
Integrity and structural checks here cannot substitute for workspace permission.
"""

from __future__ import annotations

import hashlib
import io
import math
import uuid
import zipfile
from importlib.metadata import version
from typing import Any

import numpy as np
import skops.io as sio  # type: ignore[import-untyped]
from sklearn.cluster import KMeans  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
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
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]
from sklearn.tree import (  # type: ignore[import-untyped]
    DecisionTreeClassifier,
    DecisionTreeRegressor,
)

from packages.modeling.contracts import MAX_MODEL_BYTES, ModelTrainingResult, PredictionRequest
from packages.modeling.data import ModelDataError

# Fixed code-owned allowlist, never extended from the uploaded archive's type list.
_TRUSTED_TYPES = ("numpy.dtype", "sklearn.tree._tree.Tree")
_ESTIMATORS: dict[tuple[str, str], type[Any]] = {
    ("linear_regression", "regression"): LinearRegression,
    ("decision_tree", "regression"): DecisionTreeRegressor,
    ("decision_tree", "classification"): DecisionTreeClassifier,
    ("random_forest", "regression"): RandomForestRegressor,
    ("random_forest", "classification"): RandomForestClassifier,
    ("logistic_regression", "classification"): LogisticRegression,
    ("kmeans", "clustering"): KMeans,
    ("isolation_forest", "anomaly_detection"): IsolationForest,
}


def load_internal_model(content: bytes, result: ModelTrainingResult) -> Any:
    """Validate internal metadata and archive bounds before deserializing."""
    result = ModelTrainingResult.model_validate(result.model_dump())
    manifest = result.model_file
    if (
        len(content) != manifest.size_bytes
        or hashlib.sha256(content).hexdigest() != manifest.content_digest
    ):
        raise ModelDataError("model.file_integrity_mismatch")
    if any(version(name) != expected for name, expected in manifest.dependencies.items()):
        raise ModelDataError("model.dependency_mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if (
                len(members) > 10_000
                or len({item.filename for item in members}) != len(members)
                or sum(item.file_size for item in members) > 4 * MAX_MODEL_BYTES
                or any(item.flag_bits & 1 for item in members)
            ):
                raise ModelDataError("model.archive_limit")
        unknown = sio.get_untrusted_types(data=content)
        if not set(unknown).issubset(_TRUSTED_TYPES):
            raise ModelDataError("model.untrusted_type")
        pipeline = sio.loads(content, trusted=list(_TRUSTED_TYPES))
        _validate_pipeline(pipeline, result)
        return pipeline
    except ModelDataError:
        raise
    except Exception as exc:
        # Do not include deserializer internals or model contents in user errors.
        raise ModelDataError("model.invalid_file") from exc


def _validate_pipeline(pipeline: Any, result: ModelTrainingResult) -> None:
    spec = result.spec
    if type(pipeline) is not Pipeline or [name for name, _ in pipeline.steps] != [
        "prepare",
        "model",
    ]:
        raise ModelDataError("model.pipeline_mismatch")
    estimator = pipeline.named_steps["model"]
    expected = _ESTIMATORS[(spec.algorithm, spec.task)]
    if type(estimator) is not expected:
        raise ModelDataError("model.estimator_mismatch")
    for name, value in spec.effective_parameters().items():
        if estimator.get_params()[name] != value:
            raise ModelDataError("model.parameter_mismatch")
    if spec.algorithm != "linear_regression" and estimator.random_state != spec.random_seed:
        raise ModelDataError("model.parameter_mismatch")
    if spec.algorithm in {"random_forest", "isolation_forest"} and estimator.n_jobs != 1:
        raise ModelDataError("model.parameter_mismatch")
    prepare = pipeline.named_steps["prepare"]
    if (
        type(prepare) is not ColumnTransformer
        or prepare.remainder != "drop"
        or prepare.n_features_in_ != len(spec.features)
    ):
        raise ModelDataError("model.preprocessing_mismatch")
    covered: list[int] = []
    names: list[str] = []
    for name, transformer, columns in prepare.transformers_:
        if name == "remainder" and transformer == "drop":
            if len(columns):
                raise ModelDataError("model.preprocessing_mismatch")
            continue
        if (
            name not in {"numeric", "categorical"}
            or name in names
            or type(transformer) is not Pipeline
        ):
            raise ModelDataError("model.preprocessing_mismatch")
        names.append(name)
        if any(type(index) is not int or not 0 <= index < len(spec.features) for index in columns):
            raise ModelDataError("model.preprocessing_mismatch")
        covered.extend(columns)
        expected_names = ["impute", "scale" if name == "numeric" else "encode"]
        if [step for step, _ in transformer.steps] != expected_names:
            raise ModelDataError("model.preprocessing_mismatch")
        impute, transform = (step for _, step in transformer.steps)
        if (
            type(impute) is not SimpleImputer
            or impute.strategy != ("median" if name == "numeric" else "most_frequent")
            or not impute.keep_empty_features
        ):
            raise ModelDataError("model.preprocessing_mismatch")
        if name == "numeric" and type(transform) is not StandardScaler:
            raise ModelDataError("model.preprocessing_mismatch")
        if name == "categorical" and (
            type(transform) is not OneHotEncoder
            or transform.handle_unknown != "ignore"
            or transform.max_categories != 64
            or transform.sparse_output
        ):
            raise ModelDataError("model.preprocessing_mismatch")
    if sorted(covered) != list(range(len(spec.features))):
        raise ModelDataError("model.preprocessing_mismatch")


def predict_internal_model(
    content: bytes,
    result: ModelTrainingResult,
    request: PredictionRequest,
    *,
    authorized_version_id: uuid.UUID,
) -> dict[str, object]:
    """Predict with an already authorized internal version; no network/filesystem."""
    request = PredictionRequest.model_validate(request.model_dump())
    if request.model_version_id != authorized_version_id:
        raise ModelDataError("model.version_mismatch")
    request.validate_features(result.spec.features)
    pipeline = load_internal_model(content, result)
    prepare = pipeline.named_steps["prepare"]
    numeric = {
        index
        for name, _, indices in prepare.transformers_
        if name == "numeric"
        for index in indices
    }
    rows = []
    for row in request.rows:
        values: list[object] = []
        for index, field in enumerate(result.spec.features):
            value = row[field]
            if value is None:
                values.append(np.nan)
                continue
            if index in numeric:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ModelDataError("model.feature_type_mismatch")
                try:
                    if not math.isfinite(value):
                        raise ModelDataError("model.invalid_cell")
                except OverflowError as exc:
                    raise ModelDataError("model.invalid_cell") from exc
            elif not isinstance(value, str) or not value.strip():
                raise ModelDataError("model.feature_type_mismatch")
            values.append(value)
        rows.append(values)
    x = np.array(rows, dtype=object)
    predictions = pipeline.predict(x).tolist()
    if any(isinstance(value, float) and not math.isfinite(value) for value in predictions):
        raise ModelDataError("model.nonfinite_prediction")
    output: dict[str, object] = {
        "model_version_id": str(authorized_version_id),
        "task": result.spec.task,
        "predictions": predictions,
        "row_count": len(rows),
        "warnings": list(result.warnings),
    }
    if result.spec.task == "anomaly_detection":
        scores = pipeline.decision_function(x).tolist()
        if not all(math.isfinite(value) for value in scores):
            raise ModelDataError("model.nonfinite_prediction")
        output["anomaly_scores"] = scores
    return output
