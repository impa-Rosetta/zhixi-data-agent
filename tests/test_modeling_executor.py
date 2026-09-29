import hashlib
import json
import uuid

import pytest
from pydantic import ValidationError

from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.executor import ExecutorJob, execute_job
from packages.modeling.snapshots import encode_training_snapshot
from packages.modeling.synthetic import manufacturing_training_fixture
from tests.test_modeling_training import prepared


def training_job():
    data = prepared()
    raw = manufacturing_training_fixture()
    source = VerifiedTrainingSource(
        data.spec.source_artifact_id,
        data.spec.source_snapshot_id,
        data.evidence_id,
        raw,
        data.spec.source_digest,
    )
    snapshot = encode_training_snapshot(data.spec, lambda _: source)
    job = ExecutorJob(
        job_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        operation="train",
        input_digest=snapshot.digest,
        spec=data.spec,
    )
    return job, snapshot.content


def test_executor_real_training_output_is_bound_to_attempt():
    job, content = training_job()
    result, model = execute_job(job, content)
    assert result["job_id"] == str(job.job_id)
    assert result["attempt_id"] == str(job.attempt_id)
    assert model is not None
    metadata = result["payload"]["training_result"]["model_file"]
    assert metadata["content_digest"] == hashlib.sha256(model).hexdigest()
    assert len(model) + len(json.dumps(result).encode()) < 20 * 1024 * 1024


def test_executor_rejects_bad_input_digest():
    job, content = training_job()
    with pytest.raises(ModelDataError, match="integrity"):
        execute_job(job, content + b" ")


@pytest.mark.parametrize(
    "updates",
    [
        {"command": "ls"},
        {"image": "other"},
        {"path": "/etc/passwd"},
        {"operation": "predict"},
        {"spec": None},
    ],
)
def test_executor_cannot_accept_commands_paths_or_partial_jobs(updates):
    job, _ = training_job()
    values = job.model_dump()
    values.update(updates)
    with pytest.raises(ValidationError):
        ExecutorJob.model_validate(values)


def test_executor_predict_real_saved_model():
    from packages.modeling.contracts import ModelTrainingResult, PredictionRequest

    job, content = training_job()
    trained, model = execute_job(job, content)
    result = ModelTrainingResult.model_validate(trained["payload"]["training_result"])
    version = uuid.uuid4()
    predict = ExecutorJob(
        job_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        operation="predict",
        input_digest=result.model_file.content_digest,
        model_result=result,
        model_version_id=version,
        prediction=PredictionRequest(
            model_version_id=version,
            rows=[{"downtime_minutes": 20.0, "temperature": 25.0, "line": "line-1"}],
        ),
    )
    output, file = execute_job(predict, model)
    assert file is None and len(output["payload"]["predictions"]) == 1
