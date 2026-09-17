"""Versioned, deterministic product capability answers."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    title: str
    status: Literal["available", "planned"]
    description: str
    examples: tuple[str, ...] = ()


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    product_name: str
    description: str
    capabilities: tuple[Capability, ...]
    boundaries: tuple[str, ...]


CAPABILITY_MANIFEST = CapabilityManifest(
    version="1.1.0",
    product_name="智析 Data Agent",
    description="面向企业制造质量数据的可信问析 Agent。",
    capabilities=(
        Capability(
            key="catalog",
            title="授权数据目录探索",
            status="available",
            description="查看当前工作空间已发布的数据源、表和字段目录。",
            examples=("有哪些数据源？", "inspection 表有哪些字段？"),
        ),
        Capability(
            key="metric",
            title="可信指标查询",
            status="available",
            description="通过已发布语义口径编译并执行只读指标查询。",
            examples=("分析不良率", "按产线查询一次通过率"),
        ),
        Capability(
            key="evidence",
            title="结果证据追溯",
            status="available",
            description="展示查询验证、冻结版本和执行证据。",
        ),
        Capability(
            key="analysis",
            title="高级统计分析",
            status="available",
            description="对已验证查询结果生成可追溯的描述统计摘要。",
            examples=("统计最近三个月不良率",),
        ),
        Capability(
            key="visualization",
            title="图表生成",
            status="available",
            description="基于已验证查询结果生成受限 ChartSpec 并安全渲染图表。",
            examples=("画出最近三个月不良率趋势",),
        ),
        Capability(
            key="report",
            title="报告导出",
            status="planned",
            description="Markdown、HTML 和 PDF 报告将在 M7 开放。",
        ),
    ),
    boundaries=(
        "不会绕过权限访问其他工作空间或未发布目录。",
        "不会执行任意 SQL、写操作、Shell 或模型生成代码。",
        "不会把 API Key、数据库凭据、敏感原始样例或内部推理返回到页面。",
    ),
)


def manifest_digest(manifest: CapabilityManifest) -> str:
    canonical = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def capability_response(
    manifest: CapabilityManifest = CAPABILITY_MANIFEST,
) -> dict[str, object]:
    available = [item.title for item in manifest.capabilities if item.status == "available"]
    planned = [item.title for item in manifest.capabilities if item.status == "planned"]
    examples = [
        example
        for item in manifest.capabilities
        if item.status == "available"
        for example in item.examples
    ]
    available_text = "、".join(available)
    planned_text = "、".join(planned)
    example_text = "”或“".join(examples[:3])
    message = (
        f"{manifest.product_name}是{manifest.description}"
        f"目前已支持{available_text}。"
        f"{planned_text}尚未开放，将在后续阶段接入；当前页面不会伪造这些结果。"
        f"你可以试着问：“{example_text}”。"
    )
    return {
        "message": message,
        "manifest_version": manifest.version,
        "manifest_digest": manifest_digest(manifest),
        "available": available,
        "planned": planned,
        "examples": examples,
        "boundaries": list(manifest.boundaries),
        "trust": "system",
    }
