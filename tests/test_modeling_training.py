import hashlib
import json
import uuid

import pytest

from packages.modeling.contracts import ModelSpec
from packages.modeling.data import VerifiedTrainingSource, prepare_training_data
from packages.modeling.synthetic import manufacturing_training_fixture
from packages.modeling.training import train_model


def prepared(algorithm="linear_regression", task="regression", **updates):
    data = manufacturing_training_fixture()
    digest = hashlib.sha256(
        json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    artifact, snapshot = uuid.uuid4(), uuid.uuid4()
    target = (
        "quality_label"
        if task == "classification"
        else "defect_rate"
        if task == "regression"
        else None
    )
    spec = ModelSpec(
        algorithm=algorithm,
        task=task,
        source_artifact_id=artifact,
        source_snapshot_id=snapshot,
        source_digest=digest,
        target=target,
        features=("downtime_minutes", "temperature", "line"),
        **updates,
    )
    return prepare_training_data(
        spec, lambda _: VerifiedTrainingSource(artifact, snapshot, uuid.uuid4(), data, digest)
    )


@pytest.mark.parametrize(
    "algorithm,task",
    [
        ("linear_regression", "regression"),
        ("decision_tree", "classification"),
        ("decision_tree", "regression"),
        ("random_forest", "regression"),
        ("random_forest", "classification"),
        ("logistic_regression", "classification"),
        ("kmeans", "clustering"),
        ("isolation_forest", "anomaly_detection"),
    ],
)
def test_real_algorithms_train_and_predict(algorithm, task):
    data = prepared(algorithm, task)
    output = train_model(data)
    assert output.result.sample_count == 1000
    assert len(output.model_bytes) == output.result.model_file.size_bytes
    assert len(output.pipeline.predict([[30.0, 28.0, "line-1"]])) == 1
    if task in {"regression", "classification"}:
        assert output.result.train_count == 800 and output.result.validation_count == 200
        assert output.result.baseline_metrics
        assert len(output.validation_predictions) == 200
        assert not set(output.train_indices).intersection(output.validation_indices)
    else:
        assert output.result.validation_count == 0


def test_time_split_never_trains_on_future_rows():
    output = train_model(
        prepared(split="time", time_field="observed_at", intended_use="future_prediction")
    )
    assert max(output.train_indices) < min(output.validation_indices)


def test_group_split_never_shares_equipment():
    data = prepared(split="group", group_field="device")
    output = train_model(data)
    group_column = data.columns.index("device")
    train = {data.rows[i][group_column] for i in output.train_indices}
    validation = {data.rows[i][group_column] for i in output.validation_indices}
    assert not train.intersection(validation)


def test_repeated_training_has_same_predictions():
    data = prepared()
    first, second = train_model(data), train_model(data)
    assert first.validation_predictions == second.validation_predictions
    assert first.result.metrics == second.result.metrics
