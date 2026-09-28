"""Model contracts must reject executable inputs before any training exists."""

import uuid

import pytest
from pydantic import ValidationError

from packages.modeling.contracts import (
    EvaluationMetric,
    ModelFileManifest,
    ModelSpec,
    ModelTrainingResult,
    PredictionRequest,
)


def spec(**updates):
    return {
        "algorithm": "linear_regression",
        "task": "regression",
        "source_artifact_id": str(uuid.uuid4()),
        "source_snapshot_id": str(uuid.uuid4()),
        "source_digest": "a" * 64,
        "features": ["temperature", "line"],
        "target": "defect_rate",
        **updates,
    }


@pytest.mark.parametrize(
    "algorithm,task,parameters",
    [
        ("linear_regression", "regression", {}),
        ("decision_tree", "regression", {"max_depth": 5}),
        ("decision_tree", "classification", {}),
        ("random_forest", "regression", {"n_estimators": 30}),
        ("random_forest", "classification", {}),
        ("logistic_regression", "classification", {"C": 1.0}),
        ("kmeans", "clustering", {"n_clusters": 3}),
        ("isolation_forest", "anomaly_detection", {"contamination": 0.1}),
    ],
)
def test_all_six_algorithms_accept_only_explicit_tasks(algorithm, task, parameters):
    value = ModelSpec.model_validate(
        spec(
            algorithm=algorithm,
            task=task,
            parameters=parameters,
            target="defect_rate" if task in {"regression", "classification"} else None,
        )
    )
    assert value.algorithm == algorithm
    assert value.random_seed == 42 and value.validation_fraction == 0.2
    assert ModelSpec.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "updates",
    [
        {"algorithm": "eval"},
        {"task": "forecast"},
        {"algorithm": "linear_regression", "task": "classification"},
        {"algorithm": "logistic_regression", "task": "regression"},
        {"algorithm": "kmeans", "task": "regression"},
        {"algorithm": "isolation_forest", "task": "classification"},
        {"target": None},
        {"target": "temperature"},
        {"features": []},
        {"features": ["line", "line"]},
        {"features": ["x"] * 51},
        {"features": [""]},
        {"features": ["   "]},
        {"features": [1]},
        {"source_digest": "A" * 64},
        {"source_digest": "a" * 63},
        {"source_artifact_id": "../../etc/passwd"},
        {"python": "import os"},
        {"sql": "SELECT *"},
        {"model_path": "x.pkl"},
        {"parameters": {"n_jobs": -1}},
        {"parameters": {"fit_intercept": True}},
        {"random_seed": True},
        {"random_seed": -1},
        {"random_seed": "42"},
        {"validation_fraction": True},
        {"validation_fraction": float("nan")},
        {"validation_fraction": 0.01},
        {"validation_fraction": 0.9},
        {"intended_use": "future_prediction"},
        {"split": "time"},
        {"split": "group"},
        {"split": "random", "time_field": "date"},
        {"split": "time", "time_field": "temperature"},
        {"split": "group", "group_field": "defect_rate"},
        {"split": "time", "time_field": "date", "group_field": "device"},
    ],
)
def test_invalid_model_specs_are_rejected(updates):
    with pytest.raises(ValidationError):
        ModelSpec.model_validate(spec(**updates))


@pytest.mark.parametrize(
    "algorithm,parameters",
    [
        ("decision_tree", {"max_depth": 0}),
        ("decision_tree", {"max_depth": 21}),
        ("decision_tree", {"max_depth": True}),
        ("decision_tree", {"min_samples_leaf": 0}),
        ("random_forest", {"n_estimators": 501}),
        ("random_forest", {"n_estimators": "100"}),
        ("logistic_regression", {"C": 0}),
        ("logistic_regression", {"C": float("inf")}),
        ("logistic_regression", {"max_iter": 2001}),
        ("kmeans", {"n_clusters": 1}),
        ("kmeans", {"n_clusters": 11}),
        ("kmeans", {"init": "callable"}),
        ("isolation_forest", {"contamination": 0.9}),
        ("isolation_forest", {"contamination": "auto"}),
    ],
)
def test_parameter_ranges_and_import_paths_are_not_user_controlled(algorithm, parameters):
    task = {
        "logistic_regression": "classification",
        "kmeans": "clustering",
        "isolation_forest": "anomaly_detection",
    }.get(algorithm, "regression")
    with pytest.raises(ValidationError):
        ModelSpec.model_validate(
            spec(
                algorithm=algorithm,
                task=task,
                parameters=parameters,
                target="defect_rate" if task in {"regression", "classification"} else None,
            )
        )


def test_time_and_group_split_require_non_feature_metadata():
    future = ModelSpec.model_validate(
        spec(split="time", time_field="date", intended_use="future_prediction")
    )
    assert future.time_field == "date"
    grouped = ModelSpec.model_validate(spec(split="group", group_field="device"))
    assert grouped.group_field == "device"


def manifest(**updates):
    return {
        "format": "skops",
        "content_digest": "b" * 64,
        "size_bytes": 123,
        "dependencies": {
            "scikit-learn": "1.9.1",
            "skops": "0.16.0",
            "numpy": "2.5.3",
            "scipy": "1.18.1",
        },
        **updates,
    }


def test_model_manifest_has_digest_and_fixed_dependency_set():
    value = ModelFileManifest.model_validate(manifest())
    assert value.format == "skops"


@pytest.mark.parametrize(
    "updates",
    [
        {"format": "pickle"},
        {"size_bytes": 0},
        {"size_bytes": 20 * 1024 * 1024 + 1},
        {"size_bytes": True},
        {"content_digest": "bad"},
        {"dependencies": {}},
        {"dependencies": {"scikit-learn": "latest"}},
        {"path": "/tmp/model"},
        {"trusted_types": ["os.system"]},
    ],
)
def test_model_manifest_refuses_unsafe_formats_and_missing_versions(updates):
    with pytest.raises(ValidationError):
        ModelFileManifest.model_validate(manifest(**updates))


def test_prediction_keeps_order_and_checks_exact_feature_names():
    request = PredictionRequest(
        model_version_id=uuid.uuid4(),
        rows=[
            {"temperature": 12.0, "line": "A"},
            {"temperature": None, "line": "B"},
        ],
    )
    request.validate_features(("temperature", "line"))
    assert request.rows[0]["temperature"] == 12
    with pytest.raises(ValueError, match="model.feature_mismatch"):
        request.validate_features(("temperature",))


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"x": True}],
        [{"x": float("nan")}],
        [{"x": float("inf")}],
        [{"x": []}],
        [{"x": "a" * 2001}],
        [{"": 1}],
        [{"x": 1}, {"y": 2}],
        [{f"x{i}": i for i in range(51)}],
        [{"x": 1}] * 20001,
    ],
)
def test_prediction_refuses_bad_shapes_types_and_limits(rows):
    with pytest.raises(ValidationError):
        PredictionRequest(model_version_id=uuid.uuid4(), rows=rows)


def result(**updates):
    metrics = [{"name": name, "value": 0.5} for name in ("mae", "rmse", "r2")]
    return {
        "spec": spec(),
        "model_file": manifest(),
        "total_count": 100,
        "sample_count": 100,
        "dropped_count": 0,
        "train_count": 80,
        "validation_count": 20,
        "metrics": metrics,
        "baseline_metrics": metrics,
        "warnings": ["模拟数据不代表真实业务准确率。"],
        **updates,
    }


@pytest.mark.parametrize(
    "task,algorithm,names",
    [
        ("regression", "linear_regression", ["mae", "rmse", "r2"]),
        (
            "classification",
            "logistic_regression",
            ["precision_macro", "recall_macro", "f1_macro", "roc_auc"],
        ),
        ("clustering", "kmeans", ["silhouette"]),
        ("anomaly_detection", "isolation_forest", ["anomaly_fraction"]),
    ],
)
def test_result_records_real_task_metrics_and_supervised_baseline(task, algorithm, names):
    supervised = task in {"regression", "classification"}
    metrics = [{"name": name, "value": 0.5} for name in names]
    value = ModelTrainingResult.model_validate(
        result(
            spec=spec(task=task, algorithm=algorithm, target="defect_rate" if supervised else None),
            train_count=80 if supervised else 100,
            validation_count=20 if supervised else 0,
            metrics=metrics,
            baseline_metrics=metrics if supervised else [],
        )
    )
    assert value.sample_count == value.train_count + value.validation_count


@pytest.mark.parametrize(
    "updates",
    [
        {"sample_count": 10},
        {"total_count": 101},
        {"train_count": 79},
        {"validation_count": 0, "train_count": 100},
        {"total_count": True},
        {"baseline_metrics": []},
        {"metrics": []},
        {"metrics": [{"name": "mae", "value": 0.5}]},
        {"metrics": [{"name": "mae", "value": 0.5}] * 3},
        {"metrics": [{"name": "silhouette", "value": 0.5}]},
        {"warnings": []},
        {"warnings": ["   "]},
    ],
)
def test_result_rejects_fake_counts_missing_baselines_or_wrong_metrics(updates):
    with pytest.raises(ValidationError):
        ModelTrainingResult.model_validate(result(**updates))


@pytest.mark.parametrize(
    "name,value",
    [
        ("mae", -1.0),
        ("rmse", -1.0),
        ("r2", 1.1),
        ("silhouette", -1.1),
        ("silhouette", 1.1),
        ("precision_macro", 1.1),
        ("recall_macro", -0.1),
        ("f1_macro", float("nan")),
        ("roc_auc", float("inf")),
        ("anomaly_fraction", 1.1),
        ("mae", True),
        ("mae", "1"),
    ],
)
def test_invalid_metrics_are_never_presented_as_valid(name, value):
    with pytest.raises(ValidationError):
        EvaluationMetric(name=name, value=value)


def test_undefined_metrics_require_reasons_and_negative_r2_is_valid():
    assert EvaluationMetric(name="r2", value=-5.0).value == -5.0
    assert (
        EvaluationMetric(
            name="silhouette", value=None, unavailable_reason="只有一个簇，无法计算。"
        ).value
        is None
    )
    for value, reason in [(None, None), (0.0, "undefined"), (None, "   ")]:
        with pytest.raises(ValidationError):
            EvaluationMetric(name="r2", value=value, unavailable_reason=reason)


def test_unsupervised_outputs_do_not_claim_accuracy_or_holdout_baselines():
    payload = result(
        spec=spec(algorithm="isolation_forest", task="anomaly_detection", target=None),
        train_count=100,
        validation_count=0,
        metrics=[{"name": "anomaly_fraction", "value": 0.1}],
        baseline_metrics=[],
    )
    ModelTrainingResult.model_validate(payload)
    for updates in [
        {"train_count": 80, "validation_count": 20},
        {"sample_count": 19, "total_count": 19, "train_count": 19},
        {"baseline_metrics": payload["metrics"]},
    ]:
        with pytest.raises(ValidationError):
            ModelTrainingResult.model_validate({**payload, **updates})


def test_prediction_byte_limit_and_missing_feature_check():
    with pytest.raises(ValidationError, match="model.input_too_large"):
        PredictionRequest(model_version_id=uuid.uuid4(), rows=[{"x": "a" * 2000}] * 11000)
    value = PredictionRequest(model_version_id=uuid.uuid4(), rows=[{"x": 1}])
    for features in [(), ("x", "x"), ("x", "y")]:
        with pytest.raises(ValueError, match="model.feature_mismatch"):
            value.validate_features(features)


def test_defaults_are_code_owned_and_unsupervised_target_is_rejected():
    value = ModelSpec.model_validate(spec(algorithm="random_forest"))
    assert value.effective_parameters() == {
        "max_depth": 6,
        "min_samples_leaf": 2,
        "n_estimators": 100,
    }
    with pytest.raises(ValidationError):
        ModelSpec.model_validate(spec(algorithm="kmeans", task="clustering"))
    with pytest.raises(ValidationError):
        ModelFileManifest.model_validate(
            manifest(
                dependencies={
                    "scikit-learn": "latest",
                    "skops": "0.16.0",
                    "numpy": "2.5.3",
                    "scipy": "1.18.1",
                }
            )
        )
