from pathlib import Path

import pytest

from packages.modeling.data import ModelDataError
from packages.modeling.host_policy import fixed_training_container_command

IMAGE_ID = "sha256:" + "a" * 64
NAME = "zhixi-model-" + "b" * 32


def attempt_root(tmp_path):
    root = tmp_path / "attempt"
    (root / "input").mkdir(parents=True)
    (root / "output").mkdir()
    return root


def test_fixed_runtime_is_isolated_and_does_not_mount_docker_socket(tmp_path):
    args = fixed_training_container_command(
        image_id=IMAGE_ID, container_name=NAME, attempt_root=attempt_root(tmp_path)
    )
    assert args[:2] == ("docker", "create")
    assert args[-1] == IMAGE_ID
    assert args[args.index("--network") : args.index("--network") + 2] == ("--network", "none")
    assert "--read-only" in args and "no-new-privileges" in args
    assert "--cap-drop" in args and "ALL" in args
    assert "--memory" in args and "1g" in args
    assert "--pids-limit" in args and "128" in args
    assert sum(value.startswith("type=bind,") for value in args) == 2
    assert any(value.endswith("target=/input,readonly") for value in args)
    assert all("docker.sock" not in value for value in args)


@pytest.mark.parametrize(
    "image,name",
    [
        ("python:latest", NAME),
        (IMAGE_ID, "../../evil"),
        (IMAGE_ID + ";cmd", NAME),
        (IMAGE_ID, NAME + ",--privileged"),
    ],
)
def test_unapproved_image_or_container_name_rejected(tmp_path, image, name):
    with pytest.raises(ModelDataError, match="invalid_host_job"):
        fixed_training_container_command(
            image_id=image, container_name=name, attempt_root=attempt_root(tmp_path)
        )


def test_missing_directories_and_relative_root_rejected(tmp_path):
    with pytest.raises(ModelDataError, match="invalid_attempt_root"):
        fixed_training_container_command(
            image_id=IMAGE_ID, container_name=NAME, attempt_root=Path("relative")
        )
    with pytest.raises(ModelDataError, match="invalid_attempt_root"):
        fixed_training_container_command(
            image_id=IMAGE_ID, container_name=NAME, attempt_root=tmp_path
        )
