import subprocess
from itertools import chain, repeat

import pytest

import apps.host.modeling_runtime as runtime
from packages.modeling.data import ModelDataError


class FakeProcess:
    def __init__(self, *, finish_after: int | None):
        self.finish_after = finish_after
        self.polls = 0
        self.returncode = None
        self.waited = False

    def poll(self):
        self.polls += 1
        if self.finish_after is not None and self.polls >= self.finish_after:
            self.returncode = 0
        return self.returncode

    def wait(self, *, timeout):
        self.waited = True
        self.returncode = 137
        return self.returncode


def args():
    return ("docker", "create", "--name", "zhixi-model-" + "a" * 32, "sha256:" + "b" * 64)


def test_success_starts_fixed_container_and_removes_it(monkeypatch):
    calls = []
    process = FakeProcess(finish_after=2)

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    runtime.DockerCLIModelRunner().run(args(), cancelled=lambda: False)
    assert calls[0] == args()
    assert calls[-1] == ("docker", "rm", "--force", args()[3])


@pytest.mark.parametrize("reason", ["cancelled", "timeout"])
def test_cancel_or_timeout_forcibly_removes_container(monkeypatch, reason):
    calls = []
    process = FakeProcess(finish_after=None)

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    if reason == "timeout":
        values = chain((0.0,), repeat(301.0))
        monkeypatch.setattr(runtime.time, "monotonic", lambda: next(values))
    cancelled = (lambda: True) if reason == "cancelled" else (lambda: False)
    expected = (
        "model.job_cancelled_or_revoked" if reason == "cancelled" else "model.execution_timeout"
    )
    with pytest.raises(ModelDataError, match=expected):
        runtime.DockerCLIModelRunner().run(args(), cancelled=cancelled)
    assert process.waited
    assert ("docker", "rm", "--force", args()[3]) in calls


def test_docker_create_failure_is_safe_and_does_not_try_remove(monkeypatch):
    calls = []

    def missing(command, **kwargs):
        calls.append(tuple(command))
        raise FileNotFoundError("docker unavailable")

    monkeypatch.setattr(runtime.subprocess, "run", missing)
    with pytest.raises(ModelDataError, match="model.executor_unavailable"):
        runtime.DockerCLIModelRunner().run(args(), cancelled=lambda: False)
    assert calls == [args()]
