import hashlib
import json
import uuid

import pytest

from packages.modeling.contracts import ModelSpec
from packages.modeling.data import ModelDataError, VerifiedTrainingSource, prepare_training_data


def fixture(rows=None, **updates):
    artifact, snapshot = uuid.uuid4(), uuid.uuid4()
    data = {
        "columns": ["temperature", "line", "target"],
        "rows": rows if rows is not None else [[float(i), "A", float(i * 2)] for i in range(40)],
        "truncated": False,
    }
    data["row_count"] = len(data["rows"])
    data.update(updates)
    digest = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    source = VerifiedTrainingSource(artifact, snapshot, uuid.uuid4(), data, digest)
    spec = ModelSpec(
        algorithm="linear_regression",
        task="regression",
        source_artifact_id=artifact,
        source_snapshot_id=snapshot,
        source_digest=digest,
        features=("temperature", "line"),
        target="target",
    )
    return source, spec


def test_complete_data_records_missing_without_fitting_or_imputing():
    source, spec = fixture(
        [[None if i == 0 else float(i), "A", None if i == 1 else float(i)] for i in range(40)]
    )
    result = prepare_training_data(spec, lambda _: source)
    assert result.total_count == 40 and result.dropped_count == 1
    assert result.missing_counts == {"temperature": 1, "line": 0, "target": 1}
    assert result.rows[0][0] is None
    assert result.row_indices == (0, *range(2, 40))
    assert result.feature_types == {"temperature": "numeric", "line": "categorical"}


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"truncated": True}, "model.incomplete_data"),
        ({"row_count": 41}, "model.incomplete_data"),
        ({"row_count": True}, "model.incomplete_data"),
        ({"columns": ["temperature", "temperature", "target"]}, "model.invalid_table"),
    ],
)
def test_rejects_incomplete_or_malformed_sources(updates, code):
    source, spec = fixture(**updates)
    with pytest.raises(ModelDataError, match=code):
        prepare_training_data(spec, lambda _: source)


@pytest.mark.parametrize("cell", [True, {}, float("inf"), "9"])
def test_regression_target_is_strict_numeric(cell):
    source, spec = fixture()
    source.data["rows"][0][2] = cell
    with pytest.raises(ModelDataError):
        prepare_training_data(spec, lambda _: source)


def test_loader_denial_is_not_bypassed():
    _, spec = fixture()

    def deny(_):
        raise PermissionError("denied")

    with pytest.raises(PermissionError):
        prepare_training_data(spec, deny)


def test_snapshot_and_digest_must_match():
    source, spec = fixture()
    for update in ({"source_snapshot_id": uuid.uuid4()}, {"source_digest": "a" * 64}):
        with pytest.raises(ModelDataError, match="model.source_mismatch"):
            prepare_training_data(spec.model_copy(update=update), lambda _: source)


def test_small_sample_rejected():
    source, spec = fixture([[i, "A", i] for i in range(29)])
    with pytest.raises(ModelDataError, match="model.insufficient_samples"):
        prepare_training_data(spec, lambda _: source)


def test_mixed_feature_types_rejected():
    source, spec = fixture([["hot" if i == 0 else i, "A", i] for i in range(40)])
    with pytest.raises(ModelDataError, match="model.mixed_feature_type"):
        prepare_training_data(spec, lambda _: source)


def test_classification_requires_each_class_five_samples():
    source, spec = fixture([[i, "A", "rare" if i < 4 else "normal"] for i in range(40)])
    spec = spec.model_copy(update={"algorithm": "logistic_regression", "task": "classification"})
    with pytest.raises(ModelDataError, match="model.insufficient_class_samples"):
        prepare_training_data(spec, lambda _: source)
