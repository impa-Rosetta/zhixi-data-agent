import hashlib
import uuid
from dataclasses import replace

import pytest
import skops.io as sio
from sklearn.dummy import DummyRegressor

from packages.modeling.contracts import ModelFileManifest, ModelTrainingResult, PredictionRequest
from packages.modeling.data import ModelDataError
from packages.modeling.inference import load_internal_model, predict_internal_model
from packages.modeling.training import train_model
from tests.test_modeling_training import prepared


@pytest.fixture(scope="module")
def trained():
    return train_model(prepared())


def request(**row_updates):
    return PredictionRequest(
        model_version_id=uuid.uuid4(),
        rows=[dict(downtime_minutes=30.0, temperature=28.0, line="line-1", **row_updates)],
    )


def revised(output, content=None, **updates):
    values = output.result.model_dump()
    values.update(updates)
    if content is not None:
        values["model_file"] = ModelFileManifest(
            content_digest=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            dependencies=output.result.model_file.dependencies,
        )
    return ModelTrainingResult.model_validate(values)


@pytest.mark.parametrize(
    "algorithm,task",
    [
        ("linear_regression", "regression"),
        ("decision_tree", "regression"),
        ("decision_tree", "classification"),
        ("random_forest", "regression"),
        ("random_forest", "classification"),
        ("logistic_regression", "classification"),
        ("kmeans", "clustering"),
        ("isolation_forest", "anomaly_detection"),
    ],
)
def test_safe_serialized_roundtrip(algorithm, task):
    output = train_model(prepared(algorithm, task))
    incoming = request()
    prediction = predict_internal_model(
        output.model_bytes, output.result, incoming, authorized_version_id=incoming.model_version_id
    )
    assert prediction["predictions"] == output.pipeline.predict([[30.0, 28.0, "line-1"]]).tolist()
    assert prediction["row_count"] == 1
    assert prediction["warnings"]
    if task == "anomaly_detection":
        assert len(prediction["anomaly_scores"]) == 1


def test_file_integrity_rejected_before_loading(trained, monkeypatch):
    monkeypatch.setattr(sio, "loads", lambda *args, **kwargs: pytest.fail("must not load"))
    with pytest.raises(ModelDataError, match="integrity"):
        load_internal_model(trained.model_bytes + b"x", trained.result)


def test_dependency_mismatch_before_loading(trained, monkeypatch):
    manifest = trained.result.model_file.model_dump()
    manifest["dependencies"]["numpy"] = "0.0.0"
    result = revised(trained, model_file=manifest)
    monkeypatch.setattr(sio, "loads", lambda *args, **kwargs: pytest.fail("must not load"))
    with pytest.raises(ModelDataError, match="dependency"):
        load_internal_model(trained.model_bytes, result)


def test_unknown_types_never_automatically_trusted(trained, monkeypatch):
    monkeypatch.setattr(sio, "get_untrusted_types", lambda **kwargs: ["evil.Custom"])
    monkeypatch.setattr(sio, "loads", lambda *args, **kwargs: pytest.fail("must not load"))
    with pytest.raises(ModelDataError, match="untrusted_type"):
        load_internal_model(trained.model_bytes, trained.result)


def test_wrong_estimator_rejected(trained):
    pipeline = load_internal_model(trained.model_bytes, trained.result)
    pipeline.steps[-1] = ("model", DummyRegressor())
    content = sio.dumps(pipeline)
    with pytest.raises(ModelDataError, match="estimator"):
        load_internal_model(content, revised(trained, content))


def test_version_mismatch_before_loading(trained, monkeypatch):
    monkeypatch.setattr(sio, "loads", lambda *args, **kwargs: pytest.fail("must not load"))
    with pytest.raises(ModelDataError, match="version_mismatch"):
        predict_internal_model(
            trained.model_bytes, trained.result, request(), authorized_version_id=uuid.uuid4()
        )


@pytest.mark.parametrize("value", ["30", "", True])
def test_numeric_feature_does_not_coerce(trained, value):
    data = request().model_dump()
    data["rows"][0]["downtime_minutes"] = value
    with pytest.raises(ValueError):
        incoming = PredictionRequest.model_validate(data)
        predict_internal_model(
            trained.model_bytes,
            trained.result,
            incoming,
            authorized_version_id=incoming.model_version_id,
        )


def test_missing_values_and_new_categories_supported(trained):
    incoming = request()
    incoming.rows[0]["downtime_minutes"] = None
    incoming.rows[0]["line"] = "new-line"
    output = predict_internal_model(
        trained.model_bytes,
        trained.result,
        incoming,
        authorized_version_id=incoming.model_version_id,
    )
    assert len(output["predictions"]) == 1


def test_training_imputer_statistics_use_only_train_rows():
    data = prepared(split="time", time_field="observed_at")
    rows = tuple(
        tuple(999999.0 if i >= 800 and j == 0 else value for j, value in enumerate(row))
        for i, row in enumerate(data.rows)
    )
    changed = replace(data, rows=rows)
    output = train_model(changed)
    median = sorted(row[0] for row in changed.rows[:800])
    expected = (median[399] + median[400]) / 2
    assert (
        output.pipeline.named_steps["prepare"]
        .named_transformers_["numeric"]
        .named_steps["impute"]
        .statistics_[0]
        == expected
    )
