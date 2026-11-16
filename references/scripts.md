# 脚本说明

脚本只用 Python 标准库与 `openpyxl`，都从本文件所在目录解析相对路径。
运行时不需要仓库源码，也不写插件目录以外的文件（输出位置由参数指定）。
脚本不内置任何人天数值：查基线、乘算、写入与复读校验之外的事一律不做。

## parse_docs.py

把 PRD、高阶设计与 HTML 原型解析成结构化底稿 JSON。

```text
python scripts/parse_docs.py --prd <prd.md> --hld <hld.md> --prototype <目录或文件> --out <analysis.json>
```

- `--prd` / `--hld` / `--prototype` 至少给一个；
- PRD 解析出章节与需求条目：沿用原文中的 `REQ-001` 编号；章节标题带编号时条目编号为 `REQ-001-1`；
  都没有时按顺序编号为 `R-01`；
- 高阶设计解析出「领域模型」章节下的实体与字段，以及全部 HTTP 接口（表格或行内 `GET /path` 两种写法）；
- 原型解析出每个 HTML 页面的标题、元素统计（表单、表格、按钮、输入框、下拉框、链接等）、
  标题层级、按钮文案与内部链接。

## baseline.py

读取基线工作簿，供查询任务目录、修正因子与估算参数。

```text
python scripts/baseline.py --baseline <基线.xlsx> [--search <关键词>] [--json]
```

不带 `--json` 时打印匹配行；带 `--json` 时输出结构化任务目录，便于程序消费。
库用法：

```python
from baseline import load_baseline

catalog = load_baseline("Inspire 估算基线 v0.1.xlsx")
task = catalog.lookup("普通CRUD新建")             # 按子任务类型名称精确查找
catalog.lookup("前端-页面-普通CRUD新建")           # 也接受完整路径
task.tier, task.base_name, task.unit              # 档位、任务类型基础名、计量单位
task.full_path                                    # 任务大类-任务类型-子任务类型
catalog.candidates("CRUD新建")                    # 未命中时给出同一任务类型的三档候选
catalog.factor("在遗留系统中增加功能").minimum     # 修正因子区间
catalog.parameter("设计换算系数")                  # 估算参数，缺失时返回 None
```

## build_estimate.py

按估算结果生成工作量评估工作簿，并复读校验。

```text
python scripts/build_estimate.py --estimate <estimate.json> \
    --baseline <基线.xlsx> --template <模版.xlsx> \
    --out <结果.xlsx> [--report <报告.md>]
```

行为：

1. 复制模版到输出路径，不修改模版本身；
2. 明细写入「基线任务类型」表：需求、任务说明、任务类型、设计、开发、测试、备注；
   「任务类型」列写完整路径 `任务大类-任务类型-子任务类型`；
3. 需求文字相同的相邻任务行合并成一个需求单元格（纵向合并），合并范围按需求分组推导；
   任务说明、任务类型、人天与备注仍逐行保留；
4. 设计与测试由开发人天按基线换算系数派生（估算结果给出「人天分配」时以给定值为准）；
5. 命中集成类任务类型时忽略修正场景与修正系数，并在告警中说明；
6. 「项目汇总」写入公式：设计、开发、测试为明细列求和，交付开销与项目管理开销按基线系数换算，合计为六项之和；
7. 复读产出文件，校验明细行数、每行人天、需求列合并结果与汇总公式，不一致时以非零码退出；
8. `--report` 输出逐行来源说明（需求出处、实现出处、基线人天、修正系数）与告警清单，
   同一需求的后续行在需求列以「〃」表示同上。

基线「估算参数」里缺少换算系数或开销系数时脚本直接报错，不使用内置默认值。

脚本不计算业务语义：人天、系数与占比全部来自基线文件，脚本只负责查表、乘算、写入与校验。
