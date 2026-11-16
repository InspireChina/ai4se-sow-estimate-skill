# Inspire 工作量评估

从需求文档（PRD）、技术方案高阶设计（markdown）和 HTML 原型出发，对齐 Inspire 估算基线，
生成《Inspire 工作量评估模版》并交付工作量评估文件。

- **Agent 做语义判断**：需求 → 任务 → 子任务类型 → 档位。
- **脚本做机械处理**：解析文档、查基线、写入模板、复读校验。
- **人天只来自基线工作簿**。脚本、文档与示例都不内置人天数值，调整口径时改基线文件即可。

操作步骤、输入与输出清单见 [估算指南](guide.md)。

## 目录

```text
.
├── SKILL.md                              # 技能流程：核对输入 → 解析 → 拆解 → 对齐 → 生成 → 交付
├── guide.md                              # 估算指南：输入、输出、步骤、基线维护、饺子（代号）客户专用
├── Inspire 估算基线 v0.1.xlsx            # 唯一权威：任务目录、修正因子、估算参数
├── Inspire 工作量评估模版 v0.1.xlsx      # 输出模板
├── scripts/
│   ├── parse_docs.py                     # 解析 PRD / 高阶设计 / HTML 原型
│   ├── baseline.py                       # 读取基线：任务目录、修正因子、估算参数
│   └── build_estimate.py                 # 写模板、汇总公式、复读校验、出报告
├── references/
│   ├── estimation-method.md              # 拆解与估算口径
│   ├── estimate-json.md                  # 估算结果 JSON 字段
│   └── scripts.md                        # 脚本命令与行为
├── examples/                             # 样例输入与样例产出
└── tests/                                # 最小测试集
```

本仓库本身就是一个技能：复制整个目录到宿主（Codex / Claude Code）的 skills 目录即可使用，
目录内的相对路径（`scripts/...`、`Inspire 估算基线 v0.1.xlsx`）在复制后依然成立，
不需要源码 checkout。

## 快速开始

```text
# 1. 解析输入
python scripts/parse_docs.py \
    --prd examples/prd.md --hld examples/hld.md \
    --prototype examples/prototype --out examples/output/解析底稿.json

# 2. 查询基线任务目录
python scripts/baseline.py \
    --baseline "Inspire 估算基线 v0.1.xlsx" --search 页面

# 3. 生成评估文件（estimate.json 由 Agent 按 references/estimate-json.md 编写）
python scripts/build_estimate.py \
    --estimate examples/estimate.sample.json \
    --baseline "Inspire 估算基线 v0.1.xlsx" \
    --template "Inspire 工作量评估模版 v0.1.xlsx" \
    --out examples/output/工作量评估-咨询师预约平台.xlsx \
    --report examples/output/工作量评估-咨询师预约平台.md
```

样例产出见 `examples/output/`：`examples/estimate.sample.json` 里的任务行对应的评估工作簿与报告。
样例项目为「咨询师预约平台」，覆盖终端用户端、咨询师端与管理端三个角色。
具体人天以基线工作簿当前取值为准。

## 基线维护

`Inspire 估算基线 v0.1.xlsx` 是唯一权威，三张表：

| Sheet | 内容 | 维护方式 |
|---|---|---|
| `基线任务类型` | 任务目录：任务大类、任务类型、子任务类型、基准人天、备注、评估标准、示例场景 | 直接改单元格或在表尾追加同一任务类型的三档行 |
| `修正因子` | 场景与系数（单值或区间） | 直接改单元格 |
| `估算参数` | 基线锚点与档位系数、设计与测试换算系数、交付与项目管理开销系数 | 直接改单元格 |

`基线任务类型` 的列：

| 列 | 含义 |
|---|---|
| A 任务大类 | 前端 / 后端 / 集成 / 公共能力 / 工程化 |
| B 任务类型 | 页面 / 字段 / 组件、接口 / 业务逻辑 / 异步 / 异常、系统对接、权限安全 / 平台能力、应用 |
| C 子任务类型 | 唯一的对齐键，估算结果用它查基线；含档位前缀 |
| D 基准人天（MD） | 开发人天；简单 / 普通 / 复杂三档同属一个任务类型 |
| E 备注 | 计量单位、推导（相对基线锚点的倍数）与参考标准 |
| F 评估标准 | 简单 / 普通 / 复杂三档的判定细则 |
| G 示例场景 | 交付结果、计量边界与示例 |

表头固定为这七列，后续追加内容时在表尾继续追加同一任务类型的三档行，不要改动已有行。
档位人天按基线锚点的倍数换算，锚点与系数在「估算参数」表里，推导写在「备注」列。

改完人天不必重跑任何脚本，下一次生成自然使用新值。

## 计算口径

```text
基线开发人天 = 基线[子任务类型]
开发人天 = 基线开发人天 × 修正系数 × 数量
设计人天 = 开发人天 × 设计换算系数
测试人天 = 开发人天 × 测试换算系数
交付开销 =（设计 + 开发 + 测试）× 交付开销系数
项目管理开销 =（设计 + 开发 + 测试）× 项目管理开销系数
合计 = 设计 + 开发 + 测试 + 交付开销 + 项目管理开销
```

基线只保存开发人天，设计与测试由换算系数派生。换算系数与开销系数都取自基线的「估算参数」表；
基线里缺参数时脚本直接报错，不使用内置默认值。
评估文件的第三列「任务类型」写完整路径 `任务大类-任务类型-子任务类型`。
命中集成类任务类型时不叠加修正系数，复杂度差异体现在基线档位上。
细节见 [拆解与估算口径](references/estimation-method.md)。

## 测试

```text
uv run --project . --locked pytest -c pytest.ini tests -q
```

测试覆盖解析、基线读取与生成脚本，不依赖网络或 Office。
