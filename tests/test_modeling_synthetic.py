import hashlib
import json
import uuid

import pytest

from packages.modeling.contracts import ModelSpec
from packages.modeling.data import VerifiedTrainingSource, prepare_training_data
from packages.modeling.synthetic import manufacturing_training_fixture


def test_simulated_dataset_is_reproducible_and_labeled():
    first = manufacturing_training_fixture()
    assert first == manufacturing_training_fixture()
    assert first != manufacturing_training_fixture(seed=43)
    assert first["row_count"] == 1000 and first["truncated"] is False
    assert first["simulation"]["synthetic"] is True
    assert len(first["rows"]) == 1000
    assert sum(row[-1] for row in first["rows"]) == 11
    assert len({row[0] for row in first["rows"]}) == 1000


@pytest.mark.parametrize("count", [999, 20_001, True, "1000"])
def test_out_of_budget_count_rejected(count):
    with pytest.raises(ValueError):
        manufacturing_training_fixture(count)


@pytest.mark.parametrize("seed", [-1, 2**32, True, "42"])
def test_invalid_seed_rejected(seed):
    with pytest.raises(ValueError):
        manufacturing_training_fixture(seed=seed)


@pytest.mark.parametrize(
    "algorithm,task,target",
    [
        ("linear_regression", "regression", "defect_rate"),
        ("decision_tree", "classification", "quality_label"),
        ("random_forest", "regression", "defect_rate"),
        ("logistic_regression", "classification", "quality_label"),
        ("kmeans", "clustering", None),
        ("isolation_forest", "anomaly_detection", None),
    ],
)
def test_dataset_can_be_prepared_for_all_six_algorithms(algorithm, task, target):
    data = manufacturing_training_fixture()
    digest = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    artifact, snapshot = uuid.uuid4(), uuid.uuid4()
    source = VerifiedTrainingSource(artifact, snapshot, uuid.uuid4(), data, digest)
    spec = ModelSpec(
        algorithm=algorithm,
        task=task,
        target=target,
        source_artifact_id=artifact,
        source_snapshot_id=snapshot,
        source_digest=digest,
        features=("downtime_minutes", "temperature", "line"),
    )
    prepared = prepare_training_data(spec, lambda _: source)
    assert prepared.total_count == 1000 and prepared.dropped_count == 0
    assert prepared.feature_types["line"] == "categorical"
    assert prepared.spec.target == target
