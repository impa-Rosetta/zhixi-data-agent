"""Fail when tracked or unignored project files contain high-confidence secrets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
PATTERNS = {
    "OpenAI-compatible API key": re.compile(r"(?<![A-Za-z0-9_-])sk-" + r"[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
    "AWS access key": re.compile(r"AKIA" + r"[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def candidate_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=" + ROOT.as_posix(),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [
        ROOT / line
        for line in result.stdout.splitlines()
        if line and (ROOT / line).is_file() and (ROOT / line).resolve() != SELF
    ]


def main() -> int:
    findings: list[tuple[Path, int, str]] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((path.relative_to(ROOT), line_number, name))

    if findings:
        print("Potential secrets detected (values intentionally hidden):")
        for path, line_number, name in findings:
            print(f"- {path}:{line_number}: {name}")
        return 1

    print("Secret scan passed: no high-confidence credential patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
