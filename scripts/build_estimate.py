#!/usr/bin/env python3
"""按估算结果生成《Inspire 工作量评估模版》并输出工作量评估文件。

用法：

    python build_estimate.py --estimate estimate.json \
        --baseline <Inspire 估算基线 v0.1.xlsx> \
        --template <Inspire 工作量评估模版 v0.1.xlsx> \
        --out <工作量评估.xlsx> [--report <评估报告.md>]

计算口径全部来自基线工作簿：

    开发人天 = 基线[子任务类型] × 修正系数 × 数量
    设计人天 = 开发人天 × 设计换算系数
    测试人天 = 开发人天 × 测试换算系数

脚本不内置任何人天数值，只做查表、乘算、写入与复读校验。
"""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Side

from baseline import Baseline, TaskType, load_baseline

DETAIL_SHEET = "基线任务类型"
SUMMARY_SHEET = "项目汇总"
PHASES = ("设计", "开发", "测试")

# 集成大类不叠加修正系数：基线已按对接复杂度分档，再乘系数会重复计算。
INTEGRATION_GROUP = "集成"

THIN = Side(style="thin", color="D9D9D9")
BODY_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BODY_ALIGNMENT = Alignment(vertical="top", wrap_text=True)


def _round(value: float, digits: int = 1) -> float:
    """四舍五入到指定小数位（半值进位），避免银行家舍入。"""
    quantizer = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _fmt(value: float) -> str:
    """人天展示：整数不带小数尾巴。"""
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass
class EstimateRow:
    """一条估算结果行。"""

    index: int
    requirement: str
    requirement_source: str
    description: str
    task_source: str
    subtask: str
    count: float
    base_md: float | None
    scenario: str
    correction: float
    design: float
    development: float
    testing: float
    note: str
    task_type: TaskType | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return _round(self.design + self.development + self.testing)

    @property
    def task_type_label(self) -> str:
        """评估文件「任务类型」列：任务大类 - 任务类型 - 子任务类型。"""
        if self.task_type is not None:
            return self.task_type.full_path
        return self.subtask


class EstimateError(Exception):
    """估算结果文件不满足约定结构。"""


def _load_estimate(path: Path) -> dict:
    if not path.is_file():
        raise EstimateError(f"估算结果文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise EstimateError(f"估算结果不是合法 JSON：{path}（{error}）") from error
    if not isinstance(payload, dict):
        raise EstimateError("估算结果根节点必须是对象")
    tasks = payload.get("任务")
    if not isinstance(tasks, list):
        raise EstimateError("估算结果缺少 `任务` 数组")
    return payload


def _required_parameter(catalog: Baseline, name: str) -> float:
    """读取基线「估算参数」里的系数；缺失时直接报错，不使用脚本内置默认值。"""
    value = catalog.parameter(name)
    if value is None:
        raise EstimateError(
            f"基线工作簿的「估算参数」表缺少 `{name}`，请先在基线文件里补齐再生成"
        )
    return value


def _resolve_factor(
    task: dict,
    index: int,
    catalog: Baseline,
    task_type: "TaskType | None",
    warnings: "list[str]",
) -> "tuple[str, float]":
    scenario = str(task.get("修正场景") or "").strip()
    raw_correction = task.get("修正系数")
    if task_type is not None and task_type.group == INTEGRATION_GROUP:
        if scenario or raw_correction is not None:
            warnings.append(
                f"第 {index} 行是集成类任务类型「{task_type.full_path}」，"
                "基线已按对接复杂度分档，不再叠加修正系数，已忽略"
            )
        return "", 1.0
    if not scenario:
        if raw_correction is not None:
            warnings.append(f"第 {index} 行填写了修正系数但没有修正场景，已忽略该系数")
        return "", 1.0
    factor = catalog.factor(scenario)
    if factor is None:
        warnings.append(f"第 {index} 行的修正场景不在基线修正因子表中：{scenario}")
        return scenario, float(raw_correction) if raw_correction is not None else 1.0
    if factor.minimum is None:
        warnings.append(f"第 {index} 行的修正场景系数无法解析：{scenario}")
        return scenario, float(raw_correction) if raw_correction is not None else 1.0
    if raw_correction is None:
        correction = factor.minimum
        warnings.append(f"第 {index} 行未指定修正系数，取场景 {scenario} 的下限 {correction}")
        return scenario, correction
    correction = float(raw_correction)
    if factor.maximum is not None and not (factor.minimum <= correction <= factor.maximum):
        warnings.append(
            f"第 {index} 行的修正系数 {correction} 超出场景 {scenario} 的区间 "
            f"{factor.minimum}~{factor.maximum}"
        )
    return scenario, correction


def _split_phases(
    development: float, task: dict, catalog: Baseline
) -> "tuple[float, float, float]":
    """设计、测试由开发人天按换算系数派生；也可在估算结果里直接给出三列人天。"""
    allocation = task.get("人天分配")
    if isinstance(allocation, dict) and any(
        str(allocation.get(phase, "")).strip() != "" for phase in PHASES
    ):
        values = []
        for phase in PHASES:
            raw = allocation.get(phase)
            values.append(_round(float(raw)) if raw not in (None, "") else 0.0)
        return values[0], values[1], values[2]
    design_factor = _required_parameter(catalog, "设计换算系数")
    test_factor = _required_parameter(catalog, "测试换算系数")
    design = _round(development * design_factor)
    testing = _round(development * test_factor)
    return design, development, testing


def _note_text(row: EstimateRow) -> str:
    parts = []
    if row.task_type is not None:
        parts.append(f"{row.task_type_label}（开发 {_fmt(row.base_md)} MD）")
    else:
        parts.append("基线未覆盖")
    if row.scenario:
        parts.append(f"{row.scenario}×{_fmt(row.correction)}")
    if row.count != 1:
        parts.append(f"数量×{_fmt(row.count)}")
    if row.requirement_source:
        parts.append(f"需求：{row.requirement_source}")
    if row.task_source:
        parts.append(f"实现：{row.task_source}")
    if row.note:
        parts.append(row.note)
    return "；".join(parts)


def compute_rows(payload: dict, catalog: Baseline) -> "tuple[list[EstimateRow], list[str]]":
    """把估算结果换算成人天行，并收集告警。"""
    warnings: list[str] = []
    rows: list[EstimateRow] = []
    for index, task in enumerate(payload["任务"], start=1):
        if not isinstance(task, dict):
            raise EstimateError(f"第 {index} 行不是对象")
        requirement = str(task.get("需求") or "").strip()
        subtask = str(task.get("子任务类型") or "").strip()
        if not requirement:
            raise EstimateError(f"第 {index} 行缺少 `需求`")
        if not subtask:
            raise EstimateError(f"第 {index} 行缺少 `子任务类型`")
        requirement_source = str(task.get("需求出处") or "").strip()
        task_source = str(task.get("任务出处") or "").strip()
        if not requirement_source:
            warnings.append(f"第 {index} 行缺少 `需求出处`，需求列需对齐 PRD 章节")
        if not task_source:
            warnings.append(f"第 {index} 行缺少 `任务出处`，任务列需对齐技术语言")
        count = float(task.get("数量") or 1)
        task_type = catalog.lookup(subtask)
        base_md = None
        if task_type is None:
            candidates = catalog.candidates(subtask)
            hint = "；".join(item.name for item in candidates[:6])
            warnings.append(
                f"第 {index} 行的子任务类型未命中基线：{subtask}"
                + (f"（可用：{hint}）" if hint else "")
            )
        else:
            base_md = task_type.baseline_md
            if base_md is None:
                warnings.append(f"第 {index} 行的子任务类型「{subtask}」没有基准人天，按 0 计")
                base_md = 0.0
        scenario, correction = _resolve_factor(task, index, catalog, task_type, warnings)
        development = _round((base_md or 0.0) * correction * count)
        design, development, testing = _split_phases(development, task, catalog)
        rows.append(
            EstimateRow(
                index=index,
                requirement=requirement,
                requirement_source=requirement_source,
                description=str(task.get("任务说明") or "").strip(),
                task_source=task_source,
                subtask=subtask,
                count=count,
                base_md=base_md,
                scenario=scenario,
                correction=correction,
                design=design,
                development=development,
                testing=testing,
                note=str(task.get("备注") or "").strip(),
                task_type=task_type,
            )
        )
    return rows, warnings


def write_workbook(
    template: Path, output: Path, rows: "list[EstimateRow]", catalog: Baseline
) -> None:
    """复制模板并写入明细行与项目汇总公式。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, output)
    workbook = openpyxl.load_workbook(output)
    detail = workbook[DETAIL_SHEET]
    summary = workbook[SUMMARY_SHEET]
    last_row = 1
    for row in rows:
        last_row += 1
        values = [
            row.requirement,
            row.description,
            row.task_type_label,
            row.design,
            row.development,
            row.testing,
            _note_text(row),
        ]
        for column, value in enumerate(values, start=1):
            cell = detail.cell(row=last_row, column=column, value=value)
            cell.alignment = BODY_ALIGNMENT
            cell.border = BODY_BORDER
            if column in (4, 5, 6):
                cell.number_format = "0.0"
    delivery = _required_parameter(catalog, "交付开销系数")
    management = _required_parameter(catalog, "项目管理开销系数")
    if rows:
        detail_range = f"{DETAIL_SHEET}!{{col}}2:{{col}}{last_row}"
        summary["B2"] = f"=ROUND(SUM({detail_range.format(col='D')}),1)"
        summary["B3"] = f"=ROUND(SUM({detail_range.format(col='E')}),1)"
        summary["B4"] = f"=ROUND(SUM({detail_range.format(col='F')}),1)"
        summary["B5"] = f"=ROUND((B2+B3+B4)*{delivery},1)"
        summary["B6"] = f"=ROUND((B2+B3+B4)*{management},1)"
        summary["B7"] = "=B2+B3+B4+B5+B6"
    else:
        for coordinate in ("B2", "B3", "B4", "B5", "B6", "B7"):
            summary[coordinate] = 0
    for coordinate in ("B2", "B3", "B4", "B5", "B6", "B7"):
        summary[coordinate].number_format = "0.0"
    workbook.save(output)


def verify_workbook(output: Path, rows: "list[EstimateRow]") -> "list[str]":
    """复读产出文件，校验明细行与汇总公式。"""
    problems: list[str] = []
    workbook = openpyxl.load_workbook(output, data_only=False)
    try:
        detail = workbook[DETAIL_SHEET]
        summary = workbook[SUMMARY_SHEET]
        if detail.max_row - 1 != len(rows):
            problems.append(f"明细行数不一致：文件 {detail.max_row - 1} 行，期望 {len(rows)} 行")
        for row in rows:
            excel_row = row.index + 1
            for name, column, expected in (
                ("设计", 4, row.design),
                ("开发", 5, row.development),
                ("测试", 6, row.testing),
            ):
                actual = detail.cell(row=excel_row, column=column).value
                if actual is None or abs(float(actual) - expected) > 1e-9:
                    problems.append(
                        f"第 {excel_row} 行{name}人天不一致：文件 {actual}，期望 {expected}"
                    )
        if rows:
            last = len(rows) + 1
            expected_formulas = {
                "B2": f"=ROUND(SUM({DETAIL_SHEET}!D2:D{last}),1)",
                "B3": f"=ROUND(SUM({DETAIL_SHEET}!E2:E{last}),1)",
                "B4": f"=ROUND(SUM({DETAIL_SHEET}!F2:F{last}),1)",
                "B7": "=B2+B3+B4+B5+B6",
            }
            for coordinate, formula in expected_formulas.items():
                actual = summary[coordinate].value
                if actual != formula:
                    problems.append(f"汇总 {coordinate} 公式不正确：{actual}")
        else:
            for coordinate in ("B2", "B3", "B4", "B5", "B6", "B7"):
                if summary[coordinate].value != 0:
                    problems.append(f"空估算时汇总 {coordinate} 应为 0")
    finally:
        workbook.close()
    return problems


def write_report(
    path: Path, payload: dict, rows: "list[EstimateRow]", warnings: "list[str]", catalog: Baseline
) -> None:
    """输出可读的评估报告，说明每一行的人天来源。"""
    design = _round(sum(row.design for row in rows))
    development = _round(sum(row.development for row in rows))
    testing = _round(sum(row.testing for row in rows))
    delivery = _required_parameter(catalog, "交付开销系数")
    management = _required_parameter(catalog, "项目管理开销系数")
    design_factor = _required_parameter(catalog, "设计换算系数")
    test_factor = _required_parameter(catalog, "测试换算系数")
    delivery_md = _round((design + development + testing) * delivery)
    management_md = _round((design + development + testing) * management)
    total = _round(design + development + testing + delivery_md + management_md)

    lines = [
        f"# {payload.get('项目名称', '未命名项目')} 工作量评估报告",
        "",
        f"- 项目类型：{payload.get('项目类型', '未指定')}",
        f"- 基线文件：{catalog.path}",
        f"- 任务条数：{len(rows)}",
        f"- 口径：开发取基线子任务类型人天，设计 = 开发 × {design_factor}，"
        f"测试 = 开发 × {test_factor}",
        "",
        "## 汇总（人天）",
        "",
        "| 项目 | 人天 |",
        "| --- | --- |",
        f"| 设计 | {design} |",
        f"| 开发 | {development} |",
        f"| 测试 | {testing} |",
        f"| 交付开销（系数 {delivery}） | {delivery_md} |",
        f"| 项目管理开销（系数 {management}） | {management_md} |",
        f"| **合计** | **{total}** |",
        "",
        "## 明细",
        "",
        "| # | 需求（业务语言） | 需求出处 | 任务说明（技术语言） | 实现出处 | 任务类型 | 基线开发 | 修正 | 设计 | 开发 | 测试 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        correction = f"{row.scenario}×{_fmt(row.correction)}" if row.scenario else "—"
        base = _fmt(row.base_md) if row.base_md is not None else "—"
        lines.append(
            f"| {row.index} | {row.requirement} | {row.requirement_source or '—'} | "
            f"{row.description} | {row.task_source or '—'} | {row.task_type_label} | {base} | "
            f"{correction} | {row.design} | {row.development} | {row.testing} |"
        )
    lines.append("")
    if warnings:
        lines.extend(["## 告警", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.extend(["## 告警", "", "- 无"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(arguments) -> None:
    """按命令行参数生成评估文件。"""
    catalog = load_baseline(arguments.baseline)
    payload = _load_estimate(arguments.estimate)
    rows, warnings = compute_rows(payload, catalog)
    write_workbook(arguments.template, arguments.out, rows, catalog)
    problems = verify_workbook(arguments.out, rows)
    if problems:
        for problem in problems:
            print(f"复读校验失败：{problem}")
        raise SystemExit(1)
    if arguments.report:
        write_report(arguments.report, payload, rows, warnings, catalog)
    development = _round(sum(row.development for row in rows))
    print(f"已生成工作量评估：{arguments.out}（{len(rows)} 行任务，开发 {development} MD）")
    for warning in warnings:
        print(f"告警：{warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Inspire 工作量评估文件")
    parser.add_argument("--estimate", type=Path, required=True, help="估算结果 JSON")
    parser.add_argument("--baseline", type=Path, required=True, help="Inspire 估算基线工作簿")
    parser.add_argument("--template", type=Path, required=True, help="Inspire 工作量评估模版")
    parser.add_argument("--out", type=Path, required=True, help="输出的工作量评估工作簿")
    parser.add_argument("--report", type=Path, help="同时输出评估报告 Markdown")
    arguments = parser.parse_args()
    run(arguments)


if __name__ == "__main__":
    main()
