"""基线读取：拍平后的子任务类型、任务大类边界、修正因子与估算参数。

断言以结构关系为主：基线人天由工作簿决定，测试不复制具体数值，
基线调档后仍然成立。
"""
from pathlib import Path

import pytest

from baseline import BaselineError, load_baseline

V2 = Path(__file__).resolve().parents[1]
BASELINE = V2 / "Inspire 估算基线 v0.1.xlsx"

TIERS = ("简单", "普通", "复杂")


def _catalog():
    return load_baseline(BASELINE)


def test_catalog_is_flattened_into_three_tiers():
    catalog = _catalog()
    names = [task.name for task in catalog.tasks]
    assert len(names) == len(set(names))
    assert all(task.group and task.category for task in catalog.tasks)
    grouped: dict[str, set[str]] = {}
    for task in catalog.tasks:
        grouped.setdefault(task.base_name, set()).add(task.tier)
    assert all(tiers == set(TIERS) for tiers in grouped.values())
    assert len(catalog.tasks) == 3 * len(grouped)


def test_catalog_covers_the_expected_task_groups():
    catalog = _catalog()
    groups = {task.group for task in catalog.tasks}
    assert groups == {"前端", "后端", "集成", "公共能力", "工程化"}
    assert "数据" not in groups


def test_lookup_by_name_and_tier_metadata():
    catalog = _catalog()
    task = catalog.lookup("普通CRUD新建")
    assert task is not None
    assert task.tier == "普通"
    assert task.base_name == "CRUD新建"
    assert task.group == "前端"
    assert task.category == "页面"
    assert task.development_md > 0
    assert task.unit
    assert catalog.lookup("不存在的子任务类型") is None


def test_lookup_accepts_the_full_path():
    catalog = _catalog()
    task = catalog.lookup("前端-页面-普通CRUD新建")
    assert task is not None
    assert task.full_path == "前端-页面-普通CRUD新建"
    backend = catalog.lookup("后端-接口-普通CRUD接口新建")
    assert backend is not None
    assert backend.group == "后端"


def test_lookup_ignores_surrounding_whitespace():
    catalog = _catalog()
    assert catalog.lookup("  普通CRUD新建 ") is not None


def test_tiers_follow_the_baseline_tier_factors():
    """简单档与复杂档按基线「估算参数」里的档位系数相对普通档换算。"""
    catalog = _catalog()
    simple_factor = catalog.parameter("简单档系数")
    complex_factor = catalog.parameter("复杂档系数")
    assert simple_factor is not None and complex_factor is not None
    checked = 0
    for task in catalog.tasks:
        if task.base_name != "CRUD新建":
            continue
        tiers = {item.tier: item.development_md for item in catalog.tasks if item.base_name == task.base_name}
        assert tiers["简单"] == pytest.approx(tiers["普通"] * simple_factor, rel=0.02)
        assert tiers["复杂"] == pytest.approx(tiers["普通"] * complex_factor, rel=0.02)
        checked += 1
    assert checked == len(TIERS)


def test_frontend_and_backend_crud_share_the_same_anchor():
    """前端与后端的完整 CRUD 取同一套基线锚点人天。"""
    catalog = _catalog()
    frontend = catalog.lookup("普通CRUD新建")
    backend = catalog.lookup("普通CRUD接口新建")
    assert frontend is not None and backend is not None
    assert frontend.development_md == pytest.approx(backend.development_md)
    anchor = catalog.parameter("CRUD 锚点人天")
    if anchor is not None:
        assert frontend.development_md == pytest.approx(anchor)


def test_integration_group_has_its_own_tiers():
    catalog = _catalog()
    integration = [task for task in catalog.tasks if task.group == "集成"]
    assert integration
    assert all(task.full_path.startswith("集成-") for task in integration)


def test_candidates_offer_the_three_tiers_of_one_base_name():
    catalog = _catalog()
    candidates = catalog.candidates("CRUD新建")
    assert [item.name for item in candidates] == [
        "简单CRUD新建",
        "普通CRUD新建",
        "复杂CRUD新建",
    ]
    values = [item.development_md for item in candidates]
    assert values[0] < values[1] < values[2]


def test_candidates_strip_the_tier_prefix():
    catalog = _catalog()
    assert [item.name for item in catalog.candidates("普通CRUD新建")] == [
        "简单CRUD新建",
        "普通CRUD新建",
        "复杂CRUD新建",
    ]
    assert catalog.candidates("完全不存在的类型") == []


def test_factors_and_parameters_come_from_the_workbook():
    catalog = _catalog()
    factor = catalog.factor("在遗留系统中增加功能")
    assert factor is not None
    assert factor.is_range
    assert factor.minimum < factor.maximum
    for name in ("设计换算系数", "测试换算系数", "交付开销系数", "项目管理开销系数"):
        assert catalog.parameter(name) is not None, name
    assert catalog.parameter("不存在的参数", 0.5) == 0.5


def test_missing_workbook_is_reported():
    with pytest.raises(BaselineError):
        load_baseline(V2 / "不存在.xlsx")
