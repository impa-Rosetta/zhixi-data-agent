"""Fixed Docker policy for a separate trusted host agent, never API/Worker.

Only command construction is here. The future host agent must resolve a
persisted task ID and verify the exact image ID before using this policy.
"""

from __future__ import annotations

import re
from pathlib import Path

from packages.modeling.data import ModelDataError

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER_NAME = re.compile(r"zhixi-model-[0-9a-f]{32}\Z")


def fixed_training_container_command(
    *, image_id: str, container_name: str, attempt_root: Path
) -> tuple[str, ...]:
    """Return a fixed, non-shell `docker create` argv for one attempt.

    The caller owns a fresh attempt root containing only input/ and output/.
    No path, image or runtime flag comes from user/LLM input.
    """
    if not _IMAGE_ID.fullmatch(image_id) or not _CONTAINER_NAME.fullmatch(container_name):
        raise ModelDataError("model.invalid_host_job")
    if attempt_root.is_symlink() or not attempt_root.is_absolute():
        raise ModelDataError("model.invalid_attempt_root")
    root = attempt_root.resolve(strict=True)
    inputs, outputs = root / "input", root / "output"
    if any(path.is_symlink() or not path.is_dir() for path in (inputs, outputs)):
        raise ModelDataError("model.invalid_attempt_root")
    if any(
        "," in str(path) or "\n" in str(path) or "\r" in str(path)
        for path in (root, inputs, outputs)
    ):
        raise ModelDataError("model.invalid_attempt_root")
    return (
        "docker",
        "create",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "10001:10001",
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
        "--stop-timeout",
        "10",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=134217728,uid=10001,gid=10001",
        "--mount",
        f"type=bind,source={inputs},target=/input,readonly",
        "--mount",
        f"type=bind,source={outputs},target=/output",
        image_id,
    )
