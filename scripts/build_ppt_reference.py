from pathlib import Path

from build_report_content_package import build

SOURCE = Path("docs/submission/初赛材料/给PPT同学的20页制作参考稿.md")
OUTPUT = SOURCE.with_suffix(".docx")


if __name__ == "__main__":
    build(SOURCE, OUTPUT, "智析 Data Agent 二十页 PPT 制作参考稿")
