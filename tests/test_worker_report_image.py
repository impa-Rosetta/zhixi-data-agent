from pathlib import Path


def test_worker_uses_official_https_and_bounded_apt_retries() -> None:
    dockerfile = Path("apps/worker/Dockerfile").read_text(encoding="utf-8")
    assert "s|http://deb.debian.org|https://deb.debian.org|g" in dockerfile
    assert dockerfile.count("Acquire::Retries=3") == 2
    assert dockerfile.count("Acquire::https::Timeout=30") == 2
    assert "--allow-unauthenticated" not in dockerfile
    assert "Verify-Peer=false" not in dockerfile
    assert "trusted=yes" not in dockerfile


def test_report_image_keeps_chinese_fonts_native_dependencies_and_nonroot_user() -> None:
    dockerfile = Path("apps/worker/Dockerfile").read_text(encoding="utf-8")
    for dependency in ("fonts-noto-cjk", "libpango-1.0-0", "libpangoft2-1.0-0"):
        assert dependency in dockerfile
    assert "USER zhixi" in dockerfile
    assert "COPY . " not in dockerfile
