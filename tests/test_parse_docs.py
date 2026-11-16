"""解析脚本的行为：章节、需求条目、领域模型、接口与原型页面。"""
from pathlib import Path

import parse_docs

V2 = Path(__file__).resolve().parents[1]
EXAMPLES = V2 / "examples"


def test_prd_keeps_original_requirement_ids():
    document = parse_docs.parse_requirements(EXAMPLES / "prd.md")
    identifiers = [item["编号"] for item in document["需求条目"]]
    assert "REQ-001-1" in identifiers
    assert "REQ-017-4" in identifiers
    assert len(identifiers) == len(set(identifiers))
    chapters = [chapter["标题"] for chapter in document["章节"]]
    assert any(chapter.startswith("REQ-001") for chapter in chapters)
    assert any(chapter.startswith("REQ-017") for chapter in chapters)


def test_prd_covers_three_roles():
    document = parse_docs.parse_requirements(EXAMPLES / "prd.md")
    chapters = [chapter["标题"] for chapter in document["章节"]]
    assert any("终端用户端" in chapter for chapter in chapters)
    assert any("咨询师端" in chapter for chapter in chapters)
    assert any("管理端" in chapter for chapter in chapters)


def test_prd_reads_bullets_and_table_rows(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text(
        "# 需求\n\n## 范围\n\n- 第一条需求\n- 第二条需求\n\n"
        "| 编号 | 说明 |\n| --- | --- |\n| R-01 | 表格里的需求 |\n",
        encoding="utf-8",
    )
    document = parse_docs.parse_requirements(source)
    texts = [item["文本"] for item in document["需求条目"]]
    assert "第一条需求" in texts
    assert "R-01 | 表格里的需求" in texts


def test_design_extracts_domain_models_and_apis():
    document = parse_docs.parse_design(EXAMPLES / "hld.md")
    names = [model["名称"] for model in document["领域模型"]]
    assert any(name.startswith("预约订单 Order") for name in names)
    assert any(name.startswith("可预约时段 Availability") for name in names)
    assert any(name.startswith("入驻申请 Application") for name in names)
    order = next(model for model in document["领域模型"] if model["名称"].startswith("预约订单 Order"))
    assert any(field.startswith("订单号") for field in order["字段"])
    routes = {(api["方法"], api["路径"]) for api in document["接口"]}
    assert ("GET", "/api/consultants") in routes
    assert ("POST", "/api/orders") in routes
    assert ("POST", "/api/integrations/payments") in routes


def test_design_reads_inline_api_lines(tmp_path):
    source = tmp_path / "hld.md"
    source.write_text("# 方案\n\n## 接口设计\n\n- GET /api/items 查询列表\n- POST /api/items 创建\n", encoding="utf-8")
    document = parse_docs.parse_design(source)
    routes = {(api["方法"], api["路径"]) for api in document["接口"]}
    assert ("GET", "/api/items") in routes
    assert ("POST", "/api/items") in routes


def test_prototype_counts_page_elements():
    prototype = parse_docs.parse_prototype(EXAMPLES / "prototype")
    assert prototype["页面数"] == 20
    pages = {page["文件"]: page for page in prototype["页面"]}
    assert {"user/search.html", "consultant/orders.html", "admin/reports.html"} <= set(pages)
    search = pages["user/search.html"]
    assert search["标题"].startswith("检索咨询师")
    assert search["元素统计"]["表单"] == 1
    assert search["元素统计"]["表格"] == 1
    assert search["元素统计"]["下拉框"] == 3
    detail = pages["user/order-detail.html"]
    assert detail["元素统计"]["表格"] == 3
    assert detail["元素统计"]["文本域"] == 1
    assert detail["元素统计"]["按钮"] == 2


def test_prototype_has_three_portals():
    prototype = parse_docs.parse_prototype(EXAMPLES / "prototype")
    files = [page["文件"] for page in prototype["页面"]]
    assert len([name for name in files if name.startswith("user/")]) == 7
    assert len([name for name in files if name.startswith("consultant/")]) == 6
    assert len([name for name in files if name.startswith("admin/")]) == 6


def test_analysis_bundle_keeps_all_three_inputs():
    analysis = parse_docs.build_analysis(
        EXAMPLES / "prd.md", EXAMPLES / "hld.md", EXAMPLES / "prototype"
    )
    assert set(analysis) >= {"需求文档", "技术方案", "原型"}
    assert analysis["需求文档"]["需求条目"]
    assert analysis["技术方案"]["接口"]
    assert analysis["原型"]["页面"]
