# 任务2 Agent 设计问题审查报告

## 1. 审查范围

本报告基于两类证据进行审查：

1. 题目样例题与自定义单题回放结果。
2. `predicted_eval_cases.py` 中扩展评测集及其运行输出。

同时结合当前实现代码，定位这些错误背后的 agent 设计问题，而不只停留在“哪道题答错了”。

---

## 2. 结论摘要

当前系统的主要特征是：

`样例路径表现尚可，但能力面很窄，属于“围绕少量示例题做通”的 Agent，而不是“具备完整问答能力的养老规划 Agent”。`

从你给出的结果看，有三个非常明显的信号：

1. 首批 15 题中，带明确标准答案的基础题大多能答对，说明系统在样例覆盖路径上已经做了定向适配。
2. 扩展单轮评测中，`分类覆盖 23/82`，`NLP 变体 4/10`，合计仅 `27/92`，通过率约 `29%`，说明一旦问题超出样例措辞，系统会大面积失效。
3. “校对探测”根本没有跑完，而是因为评测脚本数据结构不一致直接崩溃；这不是 agent 本身的问题，但会污染对系统质量的判断。

因此，本轮暴露出的核心问题不是单一 bug，而是整体架构上存在以下偏差：

1. 意图和题型建模不完整。
2. 工具能力设计过窄，且执行器会把复杂问题错误地“改写”为简化问题。
3. composer 不是纯展示层，而是夹带了很多硬编码业务逻辑，覆盖了真实工具结果。
4. 资产配置模块里混入了启发式假设，和题目标准口径不完全一致。
5. 评测脚本本身也有缺陷，需要和 agent 缺陷分开看。

---

## 3. 现象归纳

### 3.1 样例题命中，但泛化严重不足

样例输出中，Q1-Q8、Q10-Q11、Q14 的回答都基本符合预期；但同一套能力扩展到更完整的问题集合后，出现了成片失败：

1. 客户画像聚合题大量失败，如 `AGG02-AGG09`。
2. 行为统计题大量失败，如 `BEH05-BEH14`。
3. 养老金缺口、多人汇总、最大缺口客户等退休派生题大量失败，如 `RET06-RET10`。
4. 单产品可达标性与最优配置题大面积失败，如 `PRD01-PRD07`、`PRD09-PRD17`。
5. NLP 改写问法鲁棒性很差，如 `VAR03-VAR09`、`NLP01-NLP10` 多数失败。

这说明当前系统更像是“样例题模板匹配器”，不是“先理解任务，再调工具求值”的通用型 agent。

### 3.2 错误不是随机的，而是按模块成片出现

失败分布非常集中，说明问题出在设计层而不是偶发数值误差：

1. 画像模块不会做除年龄/收入外的大多数聚合。
2. 行为模块不会做动作级统计，只会做“偏好 Top1”和极少数聚合题。
3. 退休模块只擅长单客户点查询，不擅长 cohort 汇总、排序和场景对比。
4. 配置模块输出受硬编码模板牵引，很多问题即使底层有数据，也会被 composer 改写错。

---

## 4. 核心设计问题

## 4.1 题型建模不完整，很多问题在规划阶段就没有“合法表示”

当前 planner / router 只把问题粗分为 `profile / behavior / retirement / allocation / proposal / context / fallback`，case tag 也只覆盖了少数样例题型，见 [run.py](./run.py) 与 [llm/prompts.py](./llm/prompts.py) 的规划约束，以及 [tools/router.py](./tools/router.py) 的分类逻辑。

关键证据：

1. [tools/router.py](./tools/router.py) `169-217` 行的 `_classify()` 只有粗粒度 intent，没有“退休聚合”“行为明细统计”“客户排序”“单产品可达标性”等独立题型。
2. [orchestrator/composer.py](./orchestrator/composer.py) `136-256` 行只识别少数 case tag，如 `profile_single_value`、`retirement_required_asset`、`allocation_min_risk` 等。
3. `RET08/RET09/RET10`、`BEH14`、`NLP10` 这类“总量 / 排名 / 谁最高”问题，在现有 case tag 体系中根本没有自然落点。

直接后果：

1. 许多问题会被硬塞进相近 intent。
2. 工具调用计划缺少正确的查询目标。
3. composer 最终只能拿着不匹配的数据“猜”答案。

这也是为什么系统会出现：

1. “谁的月收入最高？”却返回“8000.00 元”而不是客户 ID。
2. “默认情景下谁的养老金缺口最大？”却返回一个金额。
3. “这 3 位客户退休至少要准备多少钱？”却只回答某一个客户的值。

结论：

`当前不是某些 case tag 缺几个，而是整个 query schema 设计不够完整。`

---

## 4.2 工具能力过窄，执行器还会把问题错误降级为“简化版问题”

这是当前系统最致命的架构问题之一。

### 4.2.1 画像聚合工具只有极少数能力

[skills/customer_profile.py](./skills/customer_profile.py) 暴露出的事实很明确：

1. `_answer_count_question()` 只支持年龄 `>= / <` 两种规则，见 `86-105` 行。
2. `_answer_avg_question()` 只支持年龄和收入平均值，见 `107-120` 行。
3. 对“平均月支出”“平均净资产”“平均结余”直接返回“暂不支持该统计维度”。

这正好解释了：

1. `AGG07` 平均月支出失败。
2. `AGG08` 平均净资产失败。
3. `AGG09` 平均月结余失败。

更严重的是，[orchestrator/executor.py](./orchestrator/executor.py) 还会进一步把 planner 输出“简化改写”：

1. `_build_count_question()` `141-151` 行只会拼年龄条件。
2. `_build_avg_question()` `154-160` 行只会拼年龄和收入。

这意味着就算 LLM planner 理解了“净资产 >= 60 万”的题意，执行器也没有对应能力，只能退化成错误或默认逻辑。

### 4.2.2 行为聚合工具只支持一个狭窄切片

[orchestrator/executor.py](./orchestrator/executor.py) `162-181` 行的 `_execute_behavior_aggregate()` 只支持：

1. `metric = avg_age`
2. 指定产品
3. 指定动作类型
4. 指定最小次数

返回值也只是 `{"query": synthetic_q, "result": result}`。

这导致系统可以勉强回答：

1. “浏览权益类产品在2次及以上的客户，他们的平均年龄是多大？”

但无法自然回答：

1. 合计购买多少次。
2. 发生过购买行为的客户有多少个。
3. 某客户浏览某类产品多少次。
4. 谁的购买次数最多。

换言之，行为能力不是“统计引擎”，只是“一个专门为 Q4 做的特例函数”。

结论：

`当前工具设计不是“能力原子化”，而是“样例题函数化”；一旦题型换壳，执行层就没有真实能力可用。`

---

## 4.3 行为模块把“偏好分析”和“动作统计”混在一起，导致大量问法答非所问

[skills/behavior_analysis.py](./skills/behavior_analysis.py) 的职责边界是混乱的：

1. `analyze()` `28-51` 行只做“Top1 偏好产品”。
2. `answer_question()` `59-75` 行如果不是少数聚合题，就直接走 `answer(customer_id)`。
3. `answer(customer_id)` `53-57` 行固定输出“行为最多的产品类型为 X”。

这就解释了几个特别典型的错误：

1. `BEH11` “客户V500002浏览权益类产品一共多少次？”返回“固收+产品”。
2. `BEH12` “客户V500003一共买过几次产品？”返回“定期存款”。
3. `BEH14` “谁的购买行为次数最多？”返回“定期存款”。

这些错误不是模型理解差，而是：

1. 模块里压根没有“单客户动作统计”能力。
2. 一旦问题没命中极少数特判，就会掉进“偏好 Top1”的默认回答路径。

这类设计缺陷非常危险，因为它会制造一种假象：

`系统不是答不出来，而是很自信地回答了另一个问题。`

在评测里，这通常比“返回不支持”更差。

---

## 4.4 退休模块是“单客户点查询引擎”，不是“退休分析引擎”

[tools/formula_engine.py](./tools/formula_engine.py) 本身的单客户测算公式并不差，`45-124` 行对月支出、所需资产、可积攒资产、缺口都有明确计算。

但系统层面的问题在于：

1. 只有 `calculate_retirement(customer_id)` 这一种工具。
2. 没有 cohort 级退休汇总工具。
3. 没有“谁的缺口最大”“哪些客户无缺口”这类分析工具。
4. composer 只认识少数退休题型，不认识“缺口 / 汇总 / 排名 / 场景问的是 gap 还是 spend”。

关键代码证据：

1. [run.py](./run.py) `117-124` 行对所有 `retirement` intent 只强制注入 `get_profile + calculate_retirement`。
2. [orchestrator/composer.py](./orchestrator/composer.py) `161-171` 行只专门处理 `duration / monthly_spend / required_asset / accumulated_asset`。
3. 并没有 `retirement_gap`、`retirement_total_required`、`retirement_max_gap_customer` 等 case tag。

这直接解释了：

1. `RET06` 问缺口，却回答了所需总资产。
2. `RET08` / `RET09` 问 3 位客户合计值，却回答了单客户数值。
3. `RET10` 问“谁的缺口最大”，却回答成金额。
4. `SCN06` 问“刚退休时每月预计要花多少钱”，却回答成退休所需总储备。

结论：

`底层公式能算，不代表 agent 具备“退休分析能力”；现在缺的是 query-to-computation 的中间层。`

---

## 4.5 composer 夹带了大量硬编码业务逻辑，覆盖了真实问题语义

理论上 composer 应该只做“基于结构化结果组织答案”。但当前 [orchestrator/composer.py](./orchestrator/composer.py) 不是这样。

最严重的几个点如下。

### 4.5.1 `allocation_goal_check` 被硬编码成“先看定期存款”

[orchestrator/composer.py](./orchestrator/composer.py) `209-245` 行里：

1. 固定取 `projection_map.get("定期存款")`。
2. 固定生成“全部投资定期存款时……”。
3. 固定再推荐“收益率最低但能达标的产品”。

这意味着，不管问题问的是：

1. 全投现金理财够不够。
2. 全投短债够不够。
3. 全投年金险够不够。
4. 全投固收+够不够。

最后都可能被回答成“全部投资定期存款时……”，这和你看到的 `PRD01-PRD07` 失败现象完全一致。

### 4.5.2 `retirement_scenario_inflation` 被硬编码成“输出 required_asset”

同文件 `247-256` 行里，不管问题问的是：

1. 缺口是多少。
2. 刚退休月支出多少。
3. 哪些客户还有/没有缺口。

只要 case tag 是 `retirement_scenario_inflation`，最终第一行就会输出：

`required_asset_at_retirement`

这正是 `SCN06` 错把“月支出”答成“所需总资产”的根因之一。

### 4.5.3 `allocation_min_risk` 输出模板会掩盖真实优化目标

`185-207` 行默认把最大仓位解释成“主力产品”，并生成固定文案：

1. “X% 的主力仓位即可覆盖养老资金需求”
2. “剩余比例用于流动性储备和长寿风险对冲”

但这个解释不一定来自优化器结果，而是 composer 的事后叙述。

这会造成两个问题：

1. 输出看起来很合理，但不一定忠实于实际求解逻辑。
2. 一旦题目要求精确比例、精确收益率、精确风险分数，模板化解释会掩盖底层错误。

结论：

`当前 composer 不是“答案渲染层”，而是“半个业务决策层”；这会让系统变得不透明且难校准。`

---

## 4.6 资产配置模块不是严格优化器，而是带强启发式的“近似求解器”

[tools/allocation_engine.py](./tools/allocation_engine.py) 暴露出两个层面的设计偏差。

### 4.6.1 `minimize_risk` 先走启发式捷径，而不是全局最优搜索

`79-89` 行显示，只要目标是 `minimize_risk`，系统会优先调用 `_build_min_risk_plan()`。

而 `_build_min_risk_plan()` `239-349` 行的逻辑是：

1. 先找“单一产品里收益率最低但能达标的产品”。
2. 再按比例回推最小需要多少主力仓位。
3. 然后把余下部分优先塞给 `现金理财` 和 `年金险`。

这本质上不是“在可行解空间里找最小风险组合”，而是：

`先选一个主力产品，再人工补一点现金和年金。`

这会直接带来：

1. `PRD12-PRD17` 这种要求精确比例、收益率、风险分数的问题大面积偏离。
2. 组合看起来“像投顾建议”，但不一定是标准答案意义下的最优解。

### 4.6.2 风险分数体系是自定义口径

`14-22` 行定义了 `_PRODUCT_RISK`，这是内部自建的风险标尺。

这本身不是错，但有两个风险：

1. 题目并没有给出这一官方评分体系。
2. 一旦标准答案不是按这个评分逻辑算的，系统就会稳定输出“自洽但不对题”的组合。

这也是为什么你会看到“最小化风险波动”类题目，经常输出一个看似能解释的方案，但和期望答案差异很大。

结论：

`当前配置模块更像“自定义投顾规则引擎”，而不是严格对齐题目口径的最优化模块。`

---

## 4.7 LLM-first 架构和当前工具面并不匹配，规划器自由度过大但执行面过窄

[orchestrator/planner.py](./orchestrator/planner.py) `26-82` 行把问题解析高度依赖 LLM 输出 JSON；[run.py](./run.py) `106-132` 行再用 `_ensure_required_tools()` 做一些兜底。

问题在于：

1. planner 看起来很自由。
2. validator 看起来很严格。
3. 但真正可执行的工具集合很窄。
4. `_ensure_required_tools()` 又只按 intent 补几个固定工具。

结果就是：

1. 前端理解层很开放。
2. 后端执行层很封闭。
3. 中间缺少一个“把 query 规范化为结构化算子”的语义层。

这会把系统拖入一种典型状态：

`LLM 理解得比工具能做的多，但执行器只能拿错误工具硬做，于是最后只能靠 composer 圆回来。`

从这轮结果看，这个问题已经成为主要瓶颈。

---

## 5. 这些问题如何映射到具体失败簇

| 失败簇 | 直接原因 | 更深层设计问题 |
| --- | --- | --- |
| `AGG02-AGG09` | 画像聚合工具不支持相关字段 | query schema 和工具原子能力不完整 |
| `BEH05-BEH14` | 行为模块只有 Top1 偏好分析，没有动作统计 | 把“偏好分析”误当成“行为统计引擎” |
| `RET06-RET10` | 退休模块只支持单客户点值，composer 不识别 gap/汇总/排名 | 缺少退休分析中间层 |
| `SCN06/SCN15` | 场景题统一走 required asset 模板 | composer 硬编码覆盖真实问题语义 |
| `PRD01-PRD07` | 单产品可达标性题被硬编码为“定期存款基线” | composer 夹带业务决策 |
| `PRD09-PRD17` | 配置求解是启发式，不是严格优化 | 配置模块和题目目标函数不一致 |
| `VAR03-VAR09`、`NLP01-NLP10` | 换一种问法就掉出特判路径 | 系统依赖样例措辞，不是真正的语义建模 |

---

## 6. 非 agent 本身的问题：评测脚本也有两个明显缺陷

这部分建议单独记，避免误判。

### 6.1 首个 sanity 脚本的命中判断会把正确答案误显示为 `?`

你给的第一段脚本里，状态判断是：

```python
status = "✓" if expected and expected in a.replace(" ", "") else "?"
```

问题在于：

1. `a.replace(" ", "")` 去掉了回答中的空格。
2. 但 `expected` 没去空格。

例如：

1. 预期是 `22 岁`
2. 实际清洗后变成 `22岁`

于是包含判断失败，显示 `?`，哪怕答案本身是对的。

这不是 agent 问题，而是评测脚本归一化不对称。

### 6.2 `calibration_probe_questions` 的数据结构和遍历逻辑不匹配

[predicted_eval_cases.py](./predicted_eval_cases.py) `293-302` 行里，`calibration_probe_questions` 是二元组：

1. `(label, question)`

但运行脚本里写的是：

```python
for label, q, expected in cases:
```

因此一定会抛出：

`ValueError: not enough values to unpack (expected 3, got 2)`

这也是你最后看到“校对探测”直接崩溃的根因。

---

## 7. 优先级最高的改造建议

如果目标是做下一轮高收益改造，我建议按下面顺序推进。

### P0. 重构 query schema，而不是继续堆 case tag

建议把问题抽象成统一查询结构，例如：

1. `domain`: profile / behavior / retirement / allocation / proposal
2. `scope`: single_customer / cohort / ranking
3. `metric`: age / net_asset / purchase_count / gap / required_asset / accumulated_asset / portfolio_return ...
4. `filters`: 风险等级、金额阈值、动作类型、产品类型、场景参数
5. `aggregation`: count / avg / sum / max / min / argmax
6. `output`: value / customer_id / explanation / portfolio

只要这个 schema 不补上，后面继续加 prompt 和特判，收益会越来越低。

### P1. 把工具改成“原子算子”，不要再让执行器拼中文问题

现在最大的结构性问题是：

`executor 通过拼中文 synthetic question 去调用 skill。`

这一步应该取消，改成真正的结构化工具，例如：

1. `profile_aggregate(field, agg, operator=None, value=None)`
2. `behavior_stat(customer_id=None, action_type=None, product=None, agg=count/sum/avg_age/argmax_customer)`
3. `retirement_stat(customer_id=None, metric=gap/required/accumulated/spend, agg=value/sum/max_customer, scenario=...)`
4. `product_feasibility(customer_id, product, scenario=...)`
5. `allocation_optimize(customer_id, objective, scenario=...)`

只要还在“先把结构化参数重新拼回中文问题”，系统就会持续丢语义。

### P1. 让 composer 只负责表述，不负责业务判断

建议把下面这些逻辑从 composer 移出去：

1. “单产品可达标性”判断。
2. “推荐哪个替代产品”。
3. “最小风险方案如何分解释文案”。
4. “场景题默认输出 required asset”。

composer 应该只做：

1. 读取已算好的结构化结果。
2. 按模板输出。

业务判断必须在 tool / engine 层完成，否则永远难以回归测试。

### P1. 资产配置改成真正的目标函数优化

对于：

1. `maximize_return`
2. `minimize_risk subject to covers_gap`

都应该有明确数学目标，而不是启发式拼装。

哪怕最后仍使用离散搜索，也应做到：

1. objective 明确。
2. constraints 明确。
3. 输出组合、收益率、风险值、是否覆盖缺口都来自同一次求解。

### P2. 把评测脚本修到“可信”，再继续做模型结论

当前至少应先修两处：

1. 命中判断的归一化。
2. `calibration_probe_questions` 的元组结构。

否则后续很多判断会混入脚本噪声。

---

## 8. 最终判断

如果从“agent 设计成熟度”而不是“样例题能否跑通”来评价，当前系统还处在：

`能力拼装型原型`，而不是 `结构完备型 Agent`。

它已经证明：

1. 单客户基础画像、基础养老公式、少量样例化行为题是可以跑通的。

但这轮输出同样清楚地证明：

1. 系统缺少完整 query schema。
2. 工具不是原子能力，而是样例题函数。
3. composer 承担了过多业务逻辑。
4. 配置模块和题目目标函数仍有偏差。

所以这份结果暴露出的不是“再补几个 if-else 就能解决”的问题，而是：

`需要把 Agent 从“示例题驱动”重构成“结构化查询驱动”。`

这是下一轮真正值得投入的方向。
