"""生成脚本的行为：写入模板、派生人天、汇总公式、复读校验与告警。

人天期望值从基线工作簿推导，测试不复制基线数值，基线调档后仍然成立。
"""
import argparse
import json
import shutil
from pathlib import Path

import openpyxl
import pytest

import build_estimate
from baseline import load_baseline

V2 = Path(__file__).resolve().parents[1]
BASELINE = V2 / "Inspire 估算基线 v0.1.xlsx"
TEMPLATE = V2 / "Inspire 工作量评估模版 v0.1.xlsx"
EXAMPLE = V2 / "examples" / "estimate.sample.json"


def _catalog():
    return load_baseline(BASELINE)


def _write_estimate(tmp_path, tasks, name="estimate.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"项目名称": "测试项目", "任务": tasks}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _build(tmp_path, tasks, report=False, baseline=BASELINE):
    estimate = _write_estimate(tmp_path, tasks)
    output = tmp_path / "结果.xlsx"
    arguments = argparse.Namespace(
        estimate=estimate,
        baseline=baseline,
        template=TEMPLATE,
        out=output,
        report=tmp_path / "报告.md" if report else None,
    )
    build_estimate.run(arguments)
    return output


def _example_tasks():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["任务"]


def test_example_estimate_fills_detail_rows_and_summary(tmp_path):
    catalog = _catalog()
    tasks = _example_tasks()
    output = _build(tmp_path, tasks, report=True)
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        summary = workbook["项目汇总"]
        assert detail.max_row == len(tasks) + 1
        assert detail["A2"].value == tasks[0]["需求"]
        assert detail["B2"].value == tasks[0]["任务说明"]
        base = catalog.lookup(tasks[0]["子任务类型"])
        assert base is not None
        assert detail["C2"].value == base.full_path
        assert detail["E2"].value == base.development_md
        assert detail["D2"].value == build_estimate._round(
            base.development_md * catalog.parameter("设计换算系数")
        )
        assert detail["F2"].value == build_estimate._round(
            base.development_md * catalog.parameter("测试换算系数")
        )
        assert "需求：" in detail["G2"].value
        assert "实现：" in detail["G2"].value
        last = len(tasks) + 1
        assert summary["B2"].value == f"=ROUND(SUM(基线任务类型!D2:D{last}),1)"
        assert summary["B3"].value == f"=ROUND(SUM(基线任务类型!E2:E{last}),1)"
        assert summary["B4"].value == f"=ROUND(SUM(基线任务类型!F2:F{last}),1)"
        assert summary["B7"].value == "=B2+B3+B4+B5+B6"
    finally:
        workbook.close()
    report = (tmp_path / "报告.md").read_text(encoding="utf-8")
    assert "工作量评估报告" in report
    assert "任务类型" in report
    assert "需求出处" in report or "PRD 2.1" in report


def test_template_header_uses_the_task_type_column():
    workbook = openpyxl.load_workbook(TEMPLATE)
    try:
        assert workbook["基线任务类型"]["C1"].value == "任务类型（用于基线对齐）"
    finally:
        workbook.close()


def test_same_requirement_is_merged_in_one_cell(tmp_path):
    """一条需求对应多个任务说明时，需求列合并成一个单元格。"""
    requirement = "用户可按状态筛选查看自己的预约订单"
    output = _build(
        tmp_path,
        [
            {
                "需求": requirement,
                "需求出处": "PRD 3. REQ-004 我的预约与订单管理",
                "任务说明": "实现我的预约页",
                "子任务类型": "普通查询列表页新建",
            },
            {
                "需求": requirement,
                "需求出处": "PRD 3. REQ-004 我的预约与订单管理",
                "任务说明": "实现订单查询接口",
                "子任务类型": "普通查询接口新建",
            },
            {
                "需求": requirement,
                "需求出处": "PRD 3. REQ-004 我的预约与订单管理",
                "任务说明": "实现订单详情接口",
                "子任务类型": "普通查询接口新建",
            },
        ],
    )
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        assert [str(item) for item in detail.merged_cells.ranges] == ["A2:A4"]
        assert detail["A2"].value == requirement
        assert detail["A3"].value is None
        assert detail["A4"].value is None
        # 合并只发生在需求列，其余列逐行保留
        assert detail["B2"].value == "实现我的预约页"
        assert detail["B4"].value == "实现订单详情接口"
        assert detail["C3"].value == "后端-接口-普通查询接口新建"
    finally:
        workbook.close()


def test_different_requirements_are_not_merged(tmp_path):
    output = _build(
        tmp_path,
        [
            {"需求": "需求一", "子任务类型": "普通查询列表页新建"},
            {"需求": "需求二", "子任务类型": "普通查询接口新建"},
        ],
    )
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        assert not list(detail.merged_cells.ranges)
        assert detail["A2"].value == "需求一"
        assert detail["A3"].value == "需求二"
    finally:
        workbook.close()


def test_example_estimate_merges_requirement_groups(tmp_path):
    """样例里一条需求对应多个任务说明，产出文件按需求合并。"""
    tasks = _example_tasks()
    output = _build(tmp_path, tasks)
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        groups = build_estimate.requirement_groups(
            build_estimate.compute_rows({"任务": tasks}, _catalog())[0]
        )
        expected = {
            f"A{group[0].index + 1}:A{group[-1].index + 1}"
            for group in groups
            if len(group) > 1
        }
        assert expected
        assert {str(item) for item in detail.merged_cells.ranges} == expected
    finally:
        workbook.close()


def test_report_shows_the_requirement_once_per_group(tmp_path):
    tasks = [
        {"需求": "同一条需求", "子任务类型": "普通查询列表页新建"},
        {"需求": "同一条需求", "子任务类型": "普通查询接口新建"},
        {"需求": "另一条需求", "子任务类型": "普通查询接口新建"},
    ]
    report = tmp_path / "报告.md"
    _build(tmp_path, tasks, report=True)
    text = report.read_text(encoding="utf-8")
    detail_lines = [line for line in text.splitlines() if line.startswith("| 1 |") or line.startswith("| 2 |") or line.startswith("| 3 |")]
    assert "| 1 | 同一条需求 |" in detail_lines[0]
    assert "| 2 | 〃 |" in detail_lines[1]
    assert "| 3 | 另一条需求 |" in detail_lines[2]


def test_template_file_is_not_modified(tmp_path):
    before = TEMPLATE.read_bytes()
    _build(tmp_path, _example_tasks())
    assert TEMPLATE.read_bytes() == before


def test_unmatched_subtask_type_warns_and_counts_zero(tmp_path):
    catalog = _catalog()
    rows, warnings = build_estimate.compute_rows(
        {"任务": [{"需求": "未覆盖的工作", "子任务类型": "不存在的类型"}]}, catalog
    )
    assert rows[0].development == 0
    assert any("未命中基线" in warning for warning in warnings)
    output = _build(tmp_path, [{"需求": "未覆盖的工作", "子任务类型": "不存在的类型"}])
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        assert detail["D2"].value == 0
        assert "基线未覆盖" in detail["G2"].value
    finally:
        workbook.close()


def test_design_and_testing_are_derived_from_development(tmp_path):
    catalog = _catalog()
    base = catalog.lookup("普通查询列表页新建")
    assert base is not None
    rows, _ = build_estimate.compute_rows(
        {
            "任务": [
                {
                    "需求": "查询列表",
                    "子任务类型": "普通查询列表页新建",
                    "数量": 2,
                }
            ]
        },
        catalog,
    )
    row = rows[0]
    assert row.development == build_estimate._round(base.development_md * 2)
    assert row.design == build_estimate._round(
        row.development * catalog.parameter("设计换算系数")
    )
    assert row.testing == build_estimate._round(
        row.development * catalog.parameter("测试换算系数")
    )


def test_correction_factor_is_applied_and_recorded(tmp_path):
    catalog = _catalog()
    base = catalog.lookup("普通查询列表页新建")
    assert base is not None
    output = _build(
        tmp_path,
        [
            {
                "需求": "遗留系统加功能",
                "子任务类型": "普通查询列表页新建",
                "修正场景": "在遗留系统中增加功能",
                "修正系数": 1.4,
            }
        ],
    )
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        assert detail["E2"].value == build_estimate._round(base.development_md * 1.4)
        assert "在遗留系统中增加功能×1.4" in detail["G2"].value
    finally:
        workbook.close()


def test_correction_factor_outside_range_warns(tmp_path):
    catalog = _catalog()
    _, warnings = build_estimate.compute_rows(
        {
            "任务": [
                {
                    "需求": "遗留系统加功能",
                    "子任务类型": "普通查询列表页新建",
                    "修正场景": "在遗留系统中增加功能",
                    "修正系数": 9.9,
                }
            ]
        },
        catalog,
    )
    assert any("超出场景" in warning for warning in warnings)


def test_correction_without_scenario_is_ignored(tmp_path):
    catalog = _catalog()
    rows, warnings = build_estimate.compute_rows(
        {
            "任务": [
                {
                    "需求": "只填系数",
                    "子任务类型": "普通查询列表页新建",
                    "修正系数": 1.4,
                }
            ]
        },
        catalog,
    )
    assert rows[0].correction == 1.0
    assert any("没有修正场景" in warning for warning in warnings)


def test_integration_task_ignores_the_correction_factor(tmp_path):
    """集成类任务类型按基线档位取值，不再叠加修正系数。"""
    catalog = _catalog()
    integration = next(task for task in catalog.tasks if task.group == "集成" and task.tier == "普通")
    rows, warnings = build_estimate.compute_rows(
        {
            "任务": [
                {
                    "需求": "跨系统对接",
                    "子任务类型": integration.name,
                    "修正场景": "不稳定系统对接（对方需定制开发）",
                    "修正系数": 1.5,
                }
            ]
        },
        catalog,
    )
    row = rows[0]
    assert row.correction == 1.0
    assert row.development == integration.development_md
    assert any("不再叠加修正系数" in warning for warning in warnings)


def test_integration_task_without_factor_is_unchanged(tmp_path):
    catalog = _catalog()
    integration = next(task for task in catalog.tasks if task.group == "集成" and task.tier == "普通")
    rows, warnings = build_estimate.compute_rows(
        {"任务": [{"需求": "跨系统对接", "子任务类型": integration.name}]}, catalog
    )
    assert rows[0].correction == 1.0
    assert rows[0].development == integration.development_md
    assert not any("不再叠加修正系数" in warning for warning in warnings)


def test_explicit_phase_allocation_wins(tmp_path):
    output = _build(
        tmp_path,
        [
            {
                "需求": "自定义拆分",
                "子任务类型": "普通查询列表页新建",
                "人天分配": {"设计": 1, "开发": 2, "测试": 0.5},
            }
        ],
    )
    workbook = openpyxl.load_workbook(output)
    try:
        detail = workbook["基线任务类型"]
        assert [detail[f"{column}2"].value for column in "DEF"] == [1, 2, 0.5]
    finally:
        workbook.close()


def test_missing_sources_warn(tmp_path):
    catalog = _catalog()
    _, warnings = build_estimate.compute_rows(
        {"任务": [{"需求": "缺出处", "子任务类型": "普通查询列表页新建"}]}, catalog
    )
    assert any("需求出处" in warning for warning in warnings)
    assert any("任务出处" in warning for warning in warnings)


def test_missing_required_field_is_rejected(tmp_path):
    without_tasks = tmp_path / "no-tasks.json"
    without_tasks.write_text(json.dumps({"项目名称": "测试项目"}), encoding="utf-8")
    with pytest.raises(build_estimate.EstimateError):
        build_estimate._load_estimate(without_tasks)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(build_estimate.EstimateError):
        build_estimate._load_estimate(broken)
    catalog = _catalog()
    with pytest.raises(build_estimate.EstimateError):
        build_estimate.compute_rows({"任务": [{"子任务类型": "普通查询列表页新建"}]}, catalog)
    with pytest.raises(build_estimate.EstimateError):
        build_estimate.compute_rows({"任务": [{"需求": "缺少类型"}]}, catalog)


def test_missing_baseline_parameter_is_rejected(tmp_path):
    """基线缺少估算参数时直接报错，不使用脚本内置默认值。"""
    stripped = tmp_path / "基线-缺参数.xlsx"
    shutil.copyfile(BASELINE, stripped)
    workbook = openpyxl.load_workbook(stripped)
    sheet = workbook["估算参数"]
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == "交付开销系数":
            sheet.cell(row=row, column=1).value = "已删除的开销系数"
    workbook.save(stripped)
    workbook.close()

    with pytest.raises(build_estimate.EstimateError):
        _build(tmp_path, _example_tasks(), baseline=stripped)


def test_recompute_is_stable(tmp_path):
    tasks = _example_tasks()
    catalog = _catalog()
    payload = {"项目名称": "测试项目", "任务": tasks}
    first, _ = build_estimate.compute_rows(payload, catalog)
    second, _ = build_estimate.compute_rows(payload, catalog)
    assert [(row.total, row.design, row.development, row.testing) for row in first] == [
        (row.total, row.design, row.development, row.testing) for row in second
    ]
    assert sum(row.total for row in first) > 0


def test_summary_totals_match_the_report(tmp_path):
    catalog = _catalog()
    report = tmp_path / "报告.md"
    output = _build(tmp_path, _example_tasks(), report=True)
    delivery = catalog.parameter("交付开销系数")
    management = catalog.parameter("项目管理开销系数")
    workbook = openpyxl.load_workbook(output, data_only=False)
    try:
        summary = workbook["项目汇总"]
        assert summary["B5"].value == f"=ROUND((B2+B3+B4)*{delivery},1)"
        assert summary["B6"].value == f"=ROUND((B2+B3+B4)*{management},1)"
    finally:
        workbook.close()

    rows, _ = build_estimate.compute_rows(
        {"项目名称": "订单中心", "任务": _example_tasks()}, catalog
    )
    design = build_estimate._round(sum(row.design for row in rows))
    development = build_estimate._round(sum(row.development for row in rows))
    testing = build_estimate._round(sum(row.testing for row in rows))
    delivery_md = build_estimate._round((design + development + testing) * delivery)
    management_md = build_estimate._round((design + development + testing) * management)
    total = build_estimate._round(design + development + testing + delivery_md + management_md)
    text = report.read_text(encoding="utf-8")
    assert f"| 开发 | {development} |" in text
    assert f"| **合计** | **{total}** |" in text
