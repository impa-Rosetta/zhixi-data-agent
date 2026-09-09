from packages.agent_core.capabilities import (
    CAPABILITY_MANIFEST,
    capability_response,
    manifest_digest,
)


def test_capability_manifest_is_versioned_deterministic_and_truthful() -> None:
    first = capability_response()
    second = capability_response()
    assert first == second
    assert first["manifest_version"] == CAPABILITY_MANIFEST.version
    assert first["manifest_digest"] == manifest_digest(CAPABILITY_MANIFEST)
    assert first["available"] == [
        "授权数据目录探索",
        "可信指标查询",
        "结果证据追溯",
    ]
    assert first["planned"] == ["高级统计分析", "图表生成", "报告导出"]
    assert "任意 SQL" in str(first["boundaries"])
    assert "尚未开放" in str(first["message"])
