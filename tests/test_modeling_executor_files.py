from pathlib import Path

import pytest

import packages.modeling.executor as executor
from packages.modeling.data import ModelDataError
from tests.test_modeling_executor import training_job


def test_main_fixed_files_success_and_exclusive_outputs(tmp_path, monkeypatch):
    job, content = training_job()
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
    (inputs / "snapshot.json").write_bytes(content)

    def mapped_path(value):
        return outputs if value == "/output" else inputs / Path(value).name

    monkeypatch.setattr(executor, "Path", mapped_path)
    monkeypatch.setenv("ZHIXI_MODEL_EXECUTOR", "isolated-v1")
    assert executor.main() == 0
    model = (outputs / "model.skops").read_bytes()
    assert executor.main() == 1
    assert (outputs / "model.skops").read_bytes() == model


def test_main_does_not_log_sensitive_invalid_job(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(executor, "Path", lambda _: tmp_path)
    monkeypatch.setenv("ZHIXI_MODEL_EXECUTOR", "isolated-v1")
    assert executor.main() == 1
    assert capsys.readouterr().out == "model.executor_failed\n"


def test_main_cannot_run_as_unconfigured_host_process(monkeypatch):
    monkeypatch.delenv("ZHIXI_MODEL_EXECUTOR", raising=False)
    with pytest.raises(ModelDataError, match="not_configured"):
        executor.main()


def test_read_rejects_directories_and_oversized_files(tmp_path):
    with pytest.raises(ModelDataError, match="invalid_input"):
        executor._read(tmp_path)
    file = tmp_path / "content"
    file.write_bytes(b"123")
    with pytest.raises(ModelDataError, match="invalid_input"):
        executor._read(file, limit=2)
    assert executor._read(file, limit=3) == b"123"
