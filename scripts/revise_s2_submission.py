"""Align the teammate's S2 draft with the repository acceptance evidence."""

# ruff: noqa: E501

import sys
from pathlib import Path

from docx import Document

SOURCE = Path(sys.argv[1])
TARGET = Path(sys.argv[2])


def replace_paragraph(paragraph, old: str, new: str) -> None:
    text = paragraph.text
    if old not in text:
        raise ValueError(f"Missing expected text: {old[:60]}")
    revised = text.replace(old, new)
    if len(paragraph.runs) == 1:
        paragraph.runs[0].text = revised
    else:
        # These are normal body/caption paragraphs; preserve paragraph styling and images.
        paragraph.runs[0].text = revised
        for run in paragraph.runs[1:]:
            run.text = ""


def main() -> None:
    document = Document(SOURCE)
    changes: dict[int, tuple[str, str]] = {
        31: (
            "合并门禁包括 Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest、Playwright、迁移往返、镜像构建、依赖审计和秘密扫描",
            "交付门禁按切片逐步执行 Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest，以及适用的 Playwright、迁移、镜像和安全检查；完整门禁将在后续总体验收中复跑",
        ),
        33: (
            "当前版本 v1.3。其余十八项指标",
            "实际版本以系统已发布语义版本为准。其余十八项指标",
        ),
        35: (
            "完整产品功能按 M7.6 至 M9 里程碑持续交付，包括统计图表收口、报告与建模、评测可观测性、产品加固与参赛交付四个阶段。",
            "当前 M7.6 统计与图表已完成阶段验收；M7.7 可信报告正在收口，随后推进隔离建模、评测可观测性和产品加固。初赛材料只展示已验收能力，未完成能力列入后续路线。",
        ),
        41: (
            "耗时扫描、查询和分析任务交给独立工作进程；后续脚本与机器学习任务放入一次性隔离沙箱",
            "耗时扫描与报告生成任务交给独立工作进程；后续脚本与机器学习任务计划放入一次性隔离沙箱",
        ),
        49: (
            "图 5  数据源接入界面（支持数据库、文件与数据接口）",
            "图 5  数据源接入目标界面（当前支持 PostgreSQL 与 MySQL；文件及数据接口待开发，效果示意待实机截图替换）",
        ),
        54: (
            "图 7  业务指标口径管理（不良率 v1.3 语义映射）",
            "图 7  业务指标口径管理（不良率语义映射；效果示意待实机截图替换）",
        ),
        61: (
            "执行过程中，工作台实时展示工具调用、SQL 执行与验证进度，用户可观察每一步的输入与结果，兼顾对话流畅性与审计可观察性。",
            "工作台已支持任务状态与事件续传、结果和证据展示；逐步工具调用、SQL 执行与验证细节按权限呈现，完整逐步可视化仍需以最终实机界面核验。",
        ),
        68: (
            "Agent 支持异常诊断，定位主要影响维度与原因，给出可执行的分析建议",
            "方案规划让 Agent 通过可验证的分组、比较与异常分析定位主要影响维度，并给出有证据约束的建议；自动根因诊断尚需专门评测",
        ),
        71: (
            "报告工具从已验证产物 组装 Markdown、HTML、PDF，保留指标口径与证据引用，不重复访问数据库。",
            "服务端报告生成核心已能从已验证产物组装 Markdown、HTML、PDF，保留指标口径与证据引用，不重复访问业务数据库；网页预览、下载和容器内中文 PDF 尚待完整实机验收。",
        ),
        79: (
            "统计与受限图表、报告生成均已通过真实链路验收；机器学习建模、隔离沙箱、黄金评测与可观测性为后续里程碑，属规划能力。",
            "统计与受限图表已有真实链路验收；报告生成服务端核心完成代码级验收，网页导出及容器内中文 PDF 仍待验证。机器学习建模、隔离沙箱、黄金评测与系统化可观测性为后续里程碑，属规划能力。",
        ),
        97: (
            "右侧按需展开计划、进度、证据、SQL 和技术详情",
            "按权限展开计划、进度、证据、SQL 和技术详情；三栏布局是目标形态，实际界面以实机截图为准",
        ),
        103: (
            "运行中允许提交并显示队列位置",
            "运行中的输入和排队行为以当前版本实测结果为准",
        ),
        107: (
            "移动端采用单栏分层导航，保证主要问答和输入框优先显示，复杂图表与证据详情可折叠展开，兼顾移动场景的可用性。",
            "移动端目标为单栏分层导航，主要问答和输入框优先显示，复杂图表与证据详情折叠展开；最终移动端适配效果以 390px 实机验收和真实截图为准。",
        ),
        120: (
            "正在进行的分析任务能够恢复继续，不丢结果，一百次至少成功九十九次。",
            "正在进行的分析任务应可恢复或给出可重试状态；一百次至少成功九十九次是后续压测目标，不是当前已达成的实测结果。",
        ),
        122: (
            "合并门禁包括 Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest、Playwright、迁移往返、镜像构建、依赖审计和秘密扫描",
            "交付门禁按切片执行 Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest，并在总体验收中补齐 Playwright、迁移往返、镜像构建、依赖审计和秘密扫描",
        ),
        137: (
            "自动候选映射，管理员确认后即可查询，验证面向未知数据的自适应能力。",
            "形成候选映射，经管理员确认、语义校验和发布后再查询。该未知数据源适配是目标验收场景，正式演示以实际打通的连接器与映射流程为准。",
        ),
        139: (
            "报告工具从已有产物组装 Markdown、HTML、PDF，保留指标口径与证据引用。",
            "报告服务端核心从已有产物组装 Markdown、HTML、PDF 并保留证据引用；用户侧下载与中文 PDF 需完成实机复验后才作为正式演示内容。",
        ),
        150: (
            "开发过程覆盖 M0 至 M9 里程碑，后端累计二百七十二项测试，并完成五轮真实 DeepSeek 验收。",
            "项目按 M0 至 M9 路线分阶段开发，M8/M9 尚未完成。截至 2026 年 9 月 20 日，后端全量 313 项测试通过；真实 DeepSeek 联调与正式演示仍需在提交版本复验。",
        ),
    }
    for index, (old, new) in changes.items():
        replace_paragraph(document.paragraphs[index], old, new)

    # Keep diagrams as diagrams. Interface/feature renderings must not be
    # presented as screenshots of already-shipped functionality.
    concept_figures = {6, 9, 10, 11, 12, 13, 14, 16, 18}
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        for figure in concept_figures:
            prefix = f"图 {figure}  "
            if text.startswith(prefix) and "待实机截图替换" not in text:
                replace_paragraph(
                    paragraph,
                    text,
                    f"{text}（产品目标效果示意，待对应功能实机验收后替换为真实截图）",
                )
                break
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    document.save(TARGET)
    print(TARGET)


if __name__ == "__main__":
    main()
