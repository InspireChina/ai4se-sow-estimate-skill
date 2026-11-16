#!/usr/bin/env python3
"""解析需求文档（PRD）、技术方案（高阶设计）与 HTML 原型，输出结构化底稿。

用法：

    python parse_docs.py --prd <prd.md> --hld <hld.md> --prototype <目录或文件> --out <底稿.json>

脚本只做机械解析：章节、需求条目、领域模型、接口、原型页面与元素统计。
任务拆解与基线对齐由 Agent 基于本底稿完成。
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+(.+?)\s*$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEPARATOR = re.compile(r"^[\s|:-]+$")
API_PATTERN = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH)\b[\s:：]+(/[^\s|`，,。]*)", re.IGNORECASE
)
REQUIREMENT_ID = re.compile(r"^([A-Z]{2,5}-\d{1,4})\b[:：、.\s]*(.*)$")
MODEL_KEYWORDS = ("领域模型", "数据模型", "领域对象", "实体模型", "领域概念", "核心领域", "实体与关系")
API_KEYWORDS = ("接口", "API", "api", "服务", "端点", "OpenAPI", "路由")


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


# --------------------------------------------------------------------------- Markdown


def _split_sections(lines: "list[str]") -> "list[dict]":
    sections: list[dict] = []
    current = {"level": 0, "title": "", "line": 0, "body": []}
    for number, raw in enumerate(lines, start=1):
        matched = HEADING.match(raw)
        if matched:
            sections.append(current)
            current = {
                "level": len(matched.group(1)),
                "title": _text(matched.group(2)),
                "line": number,
                "body": [],
            }
        else:
            current["body"].append(raw)
    sections.append(current)
    return [section for section in sections if section["level"] > 0]


def _section_items(section: dict) -> "list[str]":
    items: list[str] = []
    for raw in section["body"]:
        bullet = BULLET.match(raw)
        if bullet:
            items.append(_text(bullet.group(1)))
            continue
        table = TABLE_ROW.match(raw)
        if table and not TABLE_SEPARATOR.match(table.group(1)):
            cells = [_text(cell) for cell in table.group(1).split("|") if _text(cell)]
            if cells:
                items.append(" | ".join(cells))
    return items


def parse_markdown(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = _split_sections(lines)
    title = sections[0]["title"] if sections else path.stem
    items = []
    for section in sections:
        for item in _section_items(section):
            items.append(
                {
                    "章节": section["title"],
                    "行": section["line"],
                    "文本": item,
                }
            )
    return {
        "路径": str(path),
        "标题": title,
        "章节": [
            {"层级": section["level"], "标题": section["title"], "行": section["line"]}
            for section in sections
        ],
        "条目": items,
        "原文行数": len(lines),
    }


def _section_identifier(title: str) -> str:
    """章节标题开头带需求 ID 时取该 ID（如 `### REQ-001 订单列表查询`）。"""
    matched = REQUIREMENT_ID.match(_text(title))
    return matched.group(1) if matched else ""


def parse_requirements(path: Path) -> dict:
    """把 PRD 拆成章节与需求条目，条目编号沿用原文中的需求 ID。"""
    document = parse_markdown(path)
    requirements = []
    counter = 0
    section_counters: dict[str, int] = {}
    for item in document["条目"]:
        text = item["文本"]
        identifier = ""
        matched = REQUIREMENT_ID.match(text)
        if matched:
            identifier = matched.group(1)
            text = _text(matched.group(2)) or text
        if not identifier:
            section = item["章节"]
            section_id = _section_identifier(section)
            if section_id:
                section_counters[section] = section_counters.get(section, 0) + 1
                identifier = f"{section_id}-{section_counters[section]}"
        if not identifier:
            counter += 1
            identifier = f"R-{counter:02d}"
        requirements.append(
            {
                "编号": identifier,
                "章节": item["章节"],
                "行": item["行"],
                "文本": text,
            }
        )
    document["需求条目"] = requirements
    document.pop("条目")
    return document


def parse_design(path: Path) -> dict:
    """从高阶设计中抽取领域模型与接口清单。"""
    document = parse_markdown(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    models: list[dict] = []
    apis: list[dict] = []
    seen_api: set[tuple[str, str]] = set()

    for section in document["章节"]:
        title = section["标题"]
        is_model = any(keyword in title for keyword in MODEL_KEYWORDS)
        is_api = any(keyword in title for keyword in API_KEYWORDS)
        start = section["行"]
        end = _section_end(lines, start, section["层级"])
        for number in range(start + 1, end + 1):
            raw = lines[number - 1]
            stripped = raw.strip()
            if not stripped:
                continue
            matched = API_PATTERN.search(stripped)
            if matched:
                method = matched.group(1).upper()
                route = matched.group(2)
                remainder = stripped[matched.end() :].strip(" -—:|：,，。")
                name = remainder if not remainder.startswith("|") else ""
                key = (method, route)
                if key not in seen_api:
                    seen_api.add(key)
                    apis.append({"方法": method, "路径": route, "名称": _text(name), "行": number})
                continue
            if is_api:
                table = TABLE_ROW.match(raw)
                if table and not TABLE_SEPARATOR.match(table.group(1)):
                    cells = [_text(cell) for cell in table.group(1).split("|") if _text(cell)]
                    if len(cells) >= 2 and cells[0].upper() in {
                        "GET", "POST", "PUT", "DELETE", "PATCH"
                    }:
                        key = (cells[0].upper(), cells[1])
                        if key not in seen_api:
                            seen_api.add(key)
                            apis.append(
                                {
                                    "方法": key[0],
                                    "路径": key[1],
                                    "名称": cells[2] if len(cells) > 2 else "",
                                    "行": number,
                                }
                            )
        if is_model:
            models.extend(_extract_models(lines, section))

    document["领域模型"] = models
    document["接口"] = apis
    document.pop("条目")
    return document


def _section_end(lines: "list[str]", start: int, level: int) -> int:
    """返回章节的最后一行行号（下一个同级或更高级标题之前）。"""
    end = len(lines)
    for offset, raw in enumerate(lines[start:], start=1):
        matched = HEADING.match(raw)
        if matched and len(matched.group(1)) <= level:
            return start + offset - 1
    return end


def _extract_models(lines: "list[str]", section: dict) -> "list[dict]":
    """抽取一个「领域模型」章节下的实体与字段。"""
    entities: list[dict] = []
    start = section["行"]
    end = _section_end(lines, start, section["层级"])
    current: dict | None = None
    for number in range(start + 1, end + 1):
        raw = lines[number - 1]
        heading = HEADING.match(raw)
        if heading:
            current = {
                "名称": _text(heading.group(2)),
                "行": number,
                "字段": [],
            }
            entities.append(current)
            continue
        bullet = BULLET.match(raw)
        text = _text(bullet.group(1)) if bullet else ""
        if not text:
            table = TABLE_ROW.match(raw)
            if table and not TABLE_SEPARATOR.match(table.group(1)):
                cells = [_text(cell) for cell in table.group(1).split("|") if _text(cell)]
                text = " | ".join(cells)
        if not text:
            continue
        if current is None:
            current = {"名称": section["标题"], "行": section["行"], "字段": []}
            entities.append(current)
        current["字段"].append(text)
    return entities


# --------------------------------------------------------------------------- HTML


class _PrototypeParser(HTMLParser):
    """统计单页 HTML 原型的元素数量与结构线索。"""

    COUNT_KEYS = {
        "form": "表单",
        "table": "表格",
        "button": "按钮",
        "input": "输入框",
        "select": "下拉框",
        "textarea": "文本域",
        "a": "链接",
        "img": "图片",
        "ul": "列表",
        "ol": "列表",
        "dialog": "弹窗",
        "h1": "一级标题",
        "h2": "二级标题",
        "h3": "三级标题",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.counts: dict[str, int] = {}
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.styles: list[str] = []
        self.headings: list[str] = []
        self.buttons: list[str] = []
        self._stack: list[str] = []
        self._capture = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in self.COUNT_KEYS:
            key = self.COUNT_KEYS[tag]
            self.counts[key] = self.counts.get(key, 0) + 1
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag == "script" and attributes.get("src"):
            self.scripts.append(attributes["src"])
        if tag == "link" and attributes.get("href"):
            self.styles.append(attributes["href"])
        self._stack.append(tag)
        if tag in {"title", "h1", "h2", "h3", "button"}:
            self._capture = tag

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if self._capture == tag:
            self._capture = ""

    def handle_data(self, data):
        if not self._capture:
            return
        value = _text(data)
        if not value:
            return
        if self._capture == "title":
            self.title = f"{self.title} {value}".strip()
        elif self._capture == "button":
            self.buttons.append(value)
        else:
            self.headings.append(value)


def parse_prototype(target: Path) -> dict:
    """遍历原型目录（或单个 HTML 文件），输出页面清单与元素统计。"""
    if target.is_file():
        files = [target]
        root = target.parent
    else:
        files = sorted(target.rglob("*.html"))
        root = target
    pages = []
    for path in files:
        parser = _PrototypeParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        try:
            relative = str(path.relative_to(root))
        except ValueError:  # pragma: no cover - 不同盘符
            relative = path.name
        pages.append(
            {
                "文件": relative,
                "标题": parser.title or path.stem,
                "元素统计": parser.counts,
                "标题层级": parser.headings[:8],
                "按钮": parser.buttons[:12],
                "内部链接": [link for link in parser.links if not link.startswith(("http://", "https://", "#"))][:20],
                "脚本": parser.scripts[:10],
                "样式": parser.styles[:10],
            }
        )
    return {"入口": str(target), "页面数": len(pages), "页面": pages}


def build_analysis(prd: Path | None, hld: Path | None, prototype: Path | None) -> dict:
    analysis = {"生成时间": datetime.now().isoformat(timespec="seconds")}
    if prd:
        analysis["需求文档"] = parse_requirements(prd)
    if hld:
        analysis["技术方案"] = parse_design(hld)
    if prototype:
        analysis["原型"] = parse_prototype(prototype)
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="解析 PRD / 高阶设计 / HTML 原型")
    parser.add_argument("--prd", type=Path, help="需求文档（markdown）")
    parser.add_argument("--hld", type=Path, help="技术方案高阶设计（markdown）")
    parser.add_argument("--prototype", type=Path, help="HTML 原型目录或文件")
    parser.add_argument("--out", type=Path, required=True, help="输出的底稿 JSON")
    arguments = parser.parse_args()
    if not any([arguments.prd, arguments.hld, arguments.prototype]):
        parser.error("至少提供 --prd / --hld / --prototype 之一")
    analysis = build_analysis(arguments.prd, arguments.hld, arguments.prototype)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = []
    if "需求文档" in analysis:
        summary.append(f"需求条目 {len(analysis['需求文档']['需求条目'])} 条")
    if "技术方案" in analysis:
        summary.append(
            f"领域模型 {len(analysis['技术方案']['领域模型'])} 个 / 接口 {len(analysis['技术方案']['接口'])} 个"
        )
    if "原型" in analysis:
        summary.append(f"原型页面 {analysis['原型']['页面数']} 个")
    print(f"已写出解析底稿：{arguments.out}（{'；'.join(summary)}）")


if __name__ == "__main__":
    main()
