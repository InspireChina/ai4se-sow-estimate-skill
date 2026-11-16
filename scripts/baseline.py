"""读取 Inspire 估算基线工作簿。

基线工作簿是任务目录、修正因子和估算参数的唯一权威：
本模块只负责读取与查询，不内置任何人天数值。

目录按「任务大类 → 任务类型 → 子任务类型」组织，子任务类型拍平为简单/普通/复杂三档，
基线人天只表示开发工作量；设计与测试由估算参数里的换算系数派生。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

CATALOG_SHEET = "基线任务类型"
FACTOR_SHEET = "修正因子"
PARAM_SHEET = "估算参数"

TIER_PREFIXES = ("简单", "普通", "复杂")

_RANGE_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[-~–—至]\s*(-?\d+(?:\.\d+)?)\s*$")


class BaselineError(Exception):
    """基线工作簿无法读取或不满足约定结构。"""


@dataclass
class TaskType:
    """基线任务目录中的一行（一个拍平后的子任务类型）。"""

    group: str
    category: str
    name: str
    baseline_md: float | None
    note: str
    criteria: str
    scene: str
    unit: str = ""
    tier: str = ""
    base_name: str = ""

    @property
    def development_md(self) -> float:
        """开发人天；基线缺值时按 0 处理。"""
        return float(self.baseline_md or 0.0)

    @property
    def full_path(self) -> str:
        """任务大类 - 任务类型 - 子任务类型，用于评估文件的「任务类型」列。"""
        return f"{self.group}-{self.category}-{self.name}"


@dataclass
class Factor:
    """修正因子条目，系数可能是单值，也可能是区间。"""

    name: str
    raw: str
    minimum: float | None
    maximum: float | None

    @property
    def is_range(self) -> bool:
        return self.minimum is not None and self.maximum is not None and self.maximum > self.minimum


@dataclass
class Baseline:
    """基线工作簿的只读视图。"""

    tasks: list[TaskType] = field(default_factory=list)
    factors: dict[str, Factor] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)
    path: Path | None = None

    def lookup(self, key: str) -> TaskType | None:
        """按子任务类型名称精确查找基线行；也接受「任务大类-任务类型-子任务类型」。"""
        if not key:
            return None
        needle = key.strip()
        for task in self.tasks:
            if task.name == needle:
                return task
        collapsed = re.sub(r"\s+", "", needle).lower()
        for task in self.tasks:
            if re.sub(r"\s+", "", task.name).lower() == collapsed:
                return task
        for task in self.tasks:
            if task.full_path == needle:
                return task
        for task in self.tasks:
            if re.sub(r"\s+", "", task.full_path).lower() == collapsed:
                return task
        return None

    def candidates(self, key: str) -> list[TaskType]:
        """未精确命中时，给出同一任务类型的三档候选行。"""
        if not key:
            return []
        needle = re.sub(r"\s+", "", key).lower()
        if "-" in needle:
            # 完整路径「任务大类-任务类型-子任务类型」取最后一段
            tail = needle.rsplit("-", 1)[-1]
            if tail:
                needle = tail
        for prefix in TIER_PREFIXES:
            if needle.startswith(prefix.lower()):
                needle = needle[len(prefix) :]
        matched = [task for task in self.tasks if task.base_name.lower() == needle]
        if matched:
            return matched
        return [
            task
            for task in self.tasks
            if needle and (needle in task.name.lower() or needle in task.base_name.lower())
        ]

    def factor(self, name: str) -> Factor | None:
        if not name:
            return None
        needle = name.strip()
        for key, value in self.factors.items():
            if key == needle:
                return value
        collapsed = re.sub(r"\s+", "", needle).lower()
        for key, value in self.factors.items():
            if re.sub(r"\s+", "", key).lower() == collapsed:
                return value
        return None

    def parameter(self, name: str, default: float | None = None) -> float | None:
        for key, value in self.params.items():
            if key == name:
                return value
        return default


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_factor(raw: str) -> "tuple[float | None, float | None]":
    text = _text(raw)
    if not text:
        return None, None
    single = _number(text)
    if single is not None:
        return single, single
    matched = _RANGE_PATTERN.match(text)
    if matched:
        low, high = float(matched.group(1)), float(matched.group(2))
        return (low, high) if low <= high else (high, low)
    return None, None


def _note_unit(note: str) -> str:
    for part in re.split(r"[；;]", note):
        part = part.strip()
        if part.startswith("计量单位："):
            return part[len("计量单位：") :].strip()
    return ""


def _split_tier(name: str) -> "tuple[str, str]":
    for prefix in TIER_PREFIXES:
        if name.startswith(prefix):
            return prefix, name[len(prefix) :]
    return "", name


def load_baseline(path: str | Path) -> Baseline:
    """读取基线工作簿，返回目录、修正因子与参数。"""
    path = Path(path)
    if not path.is_file():
        raise BaselineError(f"基线工作簿不存在：{path}")
    workbook = openpyxl.load_workbook(path, data_only=True)
    try:
        if CATALOG_SHEET not in workbook.sheetnames:
            raise BaselineError(f"基线工作簿缺少 `{CATALOG_SHEET}` sheet：{path}")
        sheet = workbook[CATALOG_SHEET]
        tasks: list[TaskType] = []
        for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=7, values_only=True):
            name = _text(row[2])
            if not name:
                continue
            note = _text(row[4])
            tier, base_name = _split_tier(name)
            tasks.append(
                TaskType(
                    group=_text(row[0]),
                    category=_text(row[1]),
                    name=name,
                    baseline_md=_number(row[3]),
                    note=note,
                    criteria=_text(row[5]),
                    scene=_text(row[6]),
                    unit=_note_unit(note),
                    tier=tier,
                    base_name=base_name,
                )
            )
        factors: dict[str, Factor] = {}
        if FACTOR_SHEET in workbook.sheetnames:
            factor_sheet = workbook[FACTOR_SHEET]
            for row in factor_sheet.iter_rows(min_row=2, max_row=factor_sheet.max_row, max_col=2, values_only=True):
                name = _text(row[0])
                if not name:
                    continue
                raw = _text(row[1])
                low, high = _parse_factor(raw)
                factors[name] = Factor(name=name, raw=raw, minimum=low, maximum=high)
        params: dict[str, float] = {}
        if PARAM_SHEET in workbook.sheetnames:
            param_sheet = workbook[PARAM_SHEET]
            for row in param_sheet.iter_rows(min_row=2, max_row=param_sheet.max_row, max_col=2, values_only=True):
                name = _text(row[0])
                value = _number(row[1])
                if name and value is not None:
                    params[name] = value
    finally:
        workbook.close()
    if not tasks:
        raise BaselineError(f"基线工作簿没有任务目录数据：{path}")
    return Baseline(tasks=tasks, factors=factors, params=params, path=path)


if __name__ == "__main__":  # pragma: no cover - 手工查看目录
    import argparse
    import json

    parser = argparse.ArgumentParser(description="查看 Inspire 估算基线")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--search", default="")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    catalog = load_baseline(arguments.baseline)
    matched = [
        task
        for task in catalog.tasks
        if arguments.search in task.name or arguments.search in task.group or arguments.search in task.category
    ]
    if arguments.json:
        print(
            json.dumps(
                [
                    {
                        "任务大类": task.group,
                        "任务类型": task.category,
                        "子任务类型": task.name,
                        "完整路径": task.full_path,
                        "档位": task.tier,
                        "基准人天": task.baseline_md,
                    }
                    for task in matched
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"共 {len(catalog.tasks)} 条子任务类型，筛选出 {len(matched)} 条：")
        for task in matched:
            print(f"  [{task.group}/{task.category}] {task.name} 开发 {task.baseline_md} MD")
