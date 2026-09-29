"""Real fixed-image acceptance, without touching application DB or business volumes.

Uses fresh directories and bounded subprocess timeouts, records actual Docker inspect.
Does not serve as the production job agent or prove leases/cancellation authorization.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from packages.modeling.contracts import ModelSpec, ModelTrainingResult, PredictionRequest
from packages.modeling.data import VerifiedTrainingSource
from packages.modeling.executor import ExecutorJob
from packages.modeling.snapshots import encode_training_snapshot
from packages.modeling.synthetic import manufacturing_training_fixture

ALGORITHMS = (
    ("linear_regression", "regression"),
    ("decision_tree", "regression"),
    ("decision_tree", "classification"),
    ("random_forest", "regression"),
    ("random_forest", "classification"),
    ("logistic_regression", "classification"),
    ("kmeans", "clustering"),
    ("isolation_forest", "anomaly_detection"),
)


def docker(*args: str, timeout: int = 30) -> str:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=timeout
    ).stdout


def execute(image: str, root: Path, job: ExecutorJob, content: bytes) -> dict:
    inputs, outputs = root / "input", root / "output"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
    filename = "snapshot.json" if job.operation == "train" else "model.skops"
    (inputs / filename).write_bytes(content)
    name = "zhixi-model-accept-" + uuid.uuid4().hex
    try:
        docker(
            "create",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--cpus",
            "2",
            "--memory",
            "1g",
            "--memory-swap",
            "1g",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=134217728",
            "--mount",
            f"type=bind,source={inputs},target=/input,readonly",
            "--mount",
            f"type=bind,source={outputs},target=/output",
            image,
        )
        inspection = json.loads(docker("inspect", name))[0]
        host, config = inspection["HostConfig"], inspection["Config"]
        assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"]
        assert host["Memory"] == 1073741824 and host["PidsLimit"] == 128
        assert host["NanoCpus"] == 2000000000 and config["User"] == "10001:10001"
        assert "ALL" in host["CapDrop"]
        assert host["SecurityOpt"] == ["no-new-privileges"]
        assert all("docker.sock" not in mount["Destination"] for mount in inspection["Mounts"])
        docker("start", "--attach", name, timeout=300)
        state = json.loads(docker("inspect", name))[0]["State"]
        assert state["ExitCode"] == 0 and not state["OOMKilled"]
        files = list(outputs.iterdir())
        assert {file.name for file in files} == (
            {"result.json", "model.skops"} if job.operation == "train" else {"result.json"}
        )
        assert sum(file.stat().st_size for file in files) <= 20 * 1024 * 1024
        result = json.loads((outputs / "result.json").read_bytes())
        assert result["job_id"] == str(job.job_id) and result["attempt_id"] == str(job.attempt_id)
        return {
            "result": result,
            "config": {
                "image": inspection["Image"],
                "user": config["User"],
                "network": host["NetworkMode"],
                "memory": host["Memory"],
                "pids": host["PidsLimit"],
                "readonly": host["ReadonlyRootfs"],
                "exit_code": state["ExitCode"],
            },
        }
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=30)


def main() -> None:
    image = docker("image", "inspect", "zhixi-modeling:b4a", "--format", "{{.Id}}").strip()
    data = manufacturing_training_fixture()
    digest = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    evidence = []
    root = Path(__file__).resolve().parents[1]
    # Keep input/model bytes local, ignored by git, and avoid rewriting existing data.
    (root / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-accept-", dir=root / "tmp") as directory:
        for algorithm, task in ALGORITHMS:
            spec = ModelSpec(
                algorithm=algorithm,
                task=task,
                source_artifact_id=uuid.uuid4(),
                source_snapshot_id=uuid.uuid4(),
                source_digest=digest,
                features=("downtime_minutes", "temperature", "line"),
                target="quality_label"
                if task == "classification"
                else "defect_rate"
                if task == "regression"
                else None,
            )
            source = VerifiedTrainingSource(
                spec.source_artifact_id, spec.source_snapshot_id, uuid.uuid4(), data, digest
            )
            snapshot = encode_training_snapshot(spec, lambda _, source=source: source)
            job = ExecutorJob(
                job_id=uuid.uuid4(),
                attempt_id=uuid.uuid4(),
                operation="train",
                input_digest=snapshot.digest,
                spec=spec,
            )
            training_root = Path(directory) / f"{algorithm}-{task}-train"
            training_root.mkdir()
            trained = execute(image, training_root, job, snapshot.content)
            result = ModelTrainingResult.model_validate(
                trained["result"]["payload"]["training_result"]
            )
            model = (training_root / "output" / "model.skops").read_bytes()
            assert hashlib.sha256(model).hexdigest() == result.model_file.content_digest
            model_id = uuid.uuid4()
            incoming = PredictionRequest(
                model_version_id=model_id,
                rows=[{"downtime_minutes": 20.0, "temperature": 25.0, "line": "line-1"}],
            )
            predict_job = ExecutorJob(
                job_id=uuid.uuid4(),
                attempt_id=uuid.uuid4(),
                operation="predict",
                input_digest=result.model_file.content_digest,
                model_result=result,
                prediction=incoming,
                model_version_id=model_id,
            )
            prediction_root = Path(directory) / f"{algorithm}-{task}-predict"
            prediction_root.mkdir()
            predicted = execute(image, prediction_root, predict_job, model)
            assert predicted["result"]["payload"]["row_count"] == 1
            evidence.append(
                {
                    "algorithm": algorithm,
                    "task": task,
                    "metrics": [item.model_dump() for item in result.metrics],
                    "sample_count": result.sample_count,
                    "config": trained["config"],
                    "predictions": predicted["result"]["payload"]["predictions"],
                }
            )
            print(f"PASS {algorithm}/{task}", flush=True)
    destination = root / "docs" / "acceptance" / "evidence" / "ADV-B4a-container-2026-09-29.json"
    destination.write_text(
        json.dumps(
            {
                "simulation": True,
                "image_id": image,
                "runs": evidence,
                "not_verified": [
                    "production_agent",
                    "cancellation",
                    "lease",
                    "output_filesystem_quota",
                    "database_authorization",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
