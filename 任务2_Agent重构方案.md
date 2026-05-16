# 任务2 Agent 重构方案

## 1. 文档目标

本文档给出当前养老规划 Agent 的重构方案，目标不是继续通过规则补丁追评测一致率，而是把系统从“LLM 前置分类器 + 本地规则接管”重构为“LLM 主规划 + 确定性工具执行 + 轻量兜底”的架构。

核心目标有三项：

1. 提升语义泛化能力
2. 提升多轮上下文一致性
3. 降低新增题型与改写问法的维护成本

---

## 2. 当前问题总结

### 2.1 方向本身没有错，但落地方式偏了

让 LLM 在中间过程输出 JSON，这个思路本身是对的。

问题不在于“要不要 JSON”，而在于：

1. JSON 承载的是不是语义计划
2. JSON 是不是执行链上的单一事实来源
3. JSON 后面是否又被本地规则覆盖

当前系统的问题是：LLM 虽然输出了 JSON，但这个 JSON 更像“题型标签”，不是“语义计划”。

### 2.2 当前架构的核心症结

当前链路大致是：

1. LLM 输出 `intent/case_tag/tool_calls`
2. 本地 `local_planner` 再次判断题型并覆盖 LLM 结果
3. `run.py` 再按 `case_tag` 补工具
4. `composer` 大量使用硬编码分支直接决定答案格式甚至结论

结果是：

1. LLM 没有真正成为主规划者
2. 系统泛化能力被关键词分支限制
3. 评测一旦出现同义改写，本地规则就容易误判

### 2.3 目前暴露出的具体设计问题

#### 问题 A：Planner 不是主控制器

`orchestrator/planner.py` 先调用 LLM，但随后会与本地 planner merge。本地 planner 在多个场景下会替换 `intent/case_tag/tool_calls`，导致 LLM 规划只是“候选答案”，而不是主计划。

#### 问题 B：Local planner 承担了过多语义理解职责

`orchestrator/local_planner.py` 中存在大量基于词面的 if/elif 分支。这样的设计对样例题友好，但对改写题极不稳定。

典型后果：

1. “发生过收藏行为的客户平均年龄”类问题容易被错误分派
2. “默认情景退休总共至少要准备多少钱”类问题容易被误识别成单客户题
3. “通胀按 3% 算时哪些客户依然无缺口”类问题容易落到 fallback

#### 问题 C：Composer 过度 deterministic，LLM 作用被弱化

`orchestrator/composer.py` 虽然调用了 LLM，但大多数核心 case 最终仍走 `_deterministic_answer()`。这使得：

1. LLM 不能真正利用工具结果做自然表达
2. 系统对 phrasing 的兼容性差
3. 一些本应由 LLM 做的轻推理被写成硬编码分支

#### 问题 D：工具参数生成仍然依赖规则拼装

`behavior_query`、`retirement_query`、`product_query` 看起来已经结构化，但它们的参数并不是 LLM 直接抽出的语义槽位，而是本地 planner 通过关键词拼出来的。

因此真正的薄弱点不是“工具算不对”，而是“上游给错了参数”。

#### 问题 E：校准答案进入运行时逻辑

当前 `allocation_engine` 中存在直接读取 `calibration_3customers/customer_allocation_metrics.csv` 的路径，这能快速提高特定 benchmark 的一致率，但会显著削弱泛化能力。

这类数据应该属于：

1. 测试基准
2. 回归对照

不应该成为线上运行时的一部分。

---

## 3. 重构原则

本次重构遵循以下原则：

### 3.1 LLM 负责理解，工具负责计算

LLM 负责：

1. 识别任务类型
2. 抽取客户、过滤条件、目标、场景
3. 生成语义计划

工具负责：

1. SQL 查询
2. 行为聚合
3. 退休公式测算
4. 配置优化

### 3.2 中间 JSON 必须表达语义，而不是样例标签

不再把中间 JSON 主要设计成：

1. `case_tag`
2. 样例映射
3. 路由标签

而应该设计成：

1. 任务语义
2. 查询指标
3. 聚合方式
4. 过滤条件
5. 假设场景
6. 长期偏好

### 3.3 fallback 只做兜底，不做主逻辑

本地 planner 的职责应该收缩为：

1. LLM 不可用时的最小可运行 fallback
2. 极少数高置信字段提取
3. 调试与保底

不能再承担主规划职责。

### 3.4 benchmark 不能代替推理能力

校准集只能用于：

1. 单元测试
2. 回归评测
3. 指标对照

不能直接作为 runtime 答案来源。

---

## 4. 目标架构

重构后的目标执行链：

1. `Question`
2. `LLM Semantic Planner`
3. `Semantic Plan`
4. `Plan Compiler`
5. `Deterministic Tool Execution`
6. `Structured Results`
7. `LLM Composer`
8. `Final Answer`

其中：

1. LLM Planner 只做语义理解与规划
2. Plan Compiler 负责把语义计划编译成工具执行计划
3. Tool Executor 只做确定性计算
4. Composer 只基于结构化结果生成答案

---

## 5. 新的中间 JSON 方案

### 5.1 设计目标

中间 JSON 的职责是表达“用户到底想问什么”，而不是表达“这题像哪道样例题”。

### 5.2 推荐 Schema

```json
{
  "task": "query",
  "domain": "retirement",
  "customer_scope": {
    "type": "single",
    "customer_id": "V500001"
  },
  "query_semantics": {
    "metric": "gap",
    "aggregation": "value",
    "filters": [],
    "comparison": null
  },
  "preferences": {},
  "scenario": {
    "inflation_annual": 0.03
  },
  "response_style": "short"
}
```

### 5.3 字段解释

#### `task`

可选值：

1. `query`
2. `analyze`
3. `recommend`
4. `proposal`
5. `record_context`

#### `domain`

可选值：

1. `profile`
2. `behavior`
3. `retirement`
4. `allocation`

#### `customer_scope`

描述问题是：

1. 单客户
2. 群体
3. follow-up 指代接续

#### `query_semantics.metric`

示例：

1. `age`
2. `monthly_saving`
3. `top_product`
4. `action_count`
5. `gap`
6. `required_asset`
7. `accumulated_asset`
8. `portfolio_return`
9. `portfolio_risk`

#### `query_semantics.aggregation`

示例：

1. `value`
2. `count`
3. `avg`
4. `sum`
5. `median`
6. `argmax_customer`
7. `list_customer_ids`

#### `preferences`

长期偏好，例如：

1. `allocation_objective=minimize_risk`
2. `retirement_goal=keep_consumption`
3. `retirement_goal_monthly_expend=12000`

#### `scenario`

本轮临时假设，例如：

1. `inflation_annual=0.03`
2. `extra_monthly_saving=1000`
3. `retirement_goal_monthly_expend=15000`

---

## 6. 分阶段重构方案

## 阶段一：P0 主规划链重构

### P0-1 以 Semantic Plan 替代 case_tag 驱动

目标：

用语义中间态替代大量 `case_tag` 分支。

改动范围：

1. `llm/schemas.py`
2. `llm/validator.py`
3. `llm/prompts.py`
4. `orchestrator/planner.py`

具体动作：

1. 新增 `SemanticPlan` 数据结构
2. 废弃 planner 对几十个 `case_tag` 的强绑定
3. planner prompt 改成输出“任务语义 JSON”
4. validator 校验语义槽位，而不是优先校验 case_tag

完成标准：

1. planner 输出的核心字段是 `metric/aggregation/filters/preferences/scenario`
2. 新题型优先通过 prompt/schema 扩展，而不是加关键词

### P0-2 Local planner 降级为真正 fallback

目标：

本地 planner 只在 LLM 失败时介入。

改动范围：

1. `orchestrator/planner.py`
2. `orchestrator/local_planner.py`
3. `run.py`

具体动作：

1. 删除成功后强制 merge 的主路径
2. `local_planner` 只保留最小兜底功能
3. 避免本地 planner 覆盖 LLM 的 `intent`、`scenario`、`tool_calls`

完成标准：

1. LLM 正常返回时，本地 planner 不再参与改写
2. fallback 仅在 parse/validation 失败时使用

### P0-3 新增 Plan Compiler

目标：

把“语义理解”和“工具编排”拆开。

新增建议文件：

1. `orchestrator/plan_compiler.py`

职责：

1. 输入 `SemanticPlan`
2. 输出 `ToolExecutionPlan`

示例：

1. `metric=gap + aggregation=value + single_customer` -> `retirement_query`
2. `metric=avg_age + action=收藏` -> `behavior_query`
3. `metric=portfolio_return + allocation_objective=minimize_risk` -> `build_allocation`

完成标准：

1. planner 不再直接拼具体工具参数
2. 编译逻辑统一收敛到 compiler 层

---

## 阶段二：P1 工具层与执行层去题面化

### P1-1 工具只吃结构化参数

目标：

Skill 层与 executor 层不再读自然语言 question。

重点文件：

1. `skills/customer_profile.py`
2. `skills/behavior_analysis.py`
3. `skills/retirement_calc.py`
4. `orchestrator/executor.py`

具体动作：

1. 废弃 `_answer_xxx_question()` 风格接口
2. 保留 `query(params)` 风格接口
3. 所有工具参数由 compiler 提供

完成标准：

1. 自然语言只在 planner 出现一次
2. skill/executor 不再二次猜题意

### P1-2 行为查询参数语义标准化

建议统一为如下结构：

```json
{
  "metric": "avg_age",
  "action_type": "收藏",
  "product": null,
  "scope": "cohort",
  "customer_id": null,
  "threshold": {
    "op": ">=",
    "value": 1
  }
}
```

收益：

1. “买过产品的客户平均年龄是多少”
2. “样本里发生过收藏的客户，平均年龄多大”
3. “浏览权益类产品在2次及以上的客户，他们的平均年龄是多大”

都能走同一语义路径。

### P1-3 退休查询参数语义标准化

建议统一为如下结构：

```json
{
  "metric": "required_asset",
  "aggregation": "sum",
  "scope": "cohort",
  "customer_id": null,
  "scenario": {
    "inflation_annual": 0.03
  }
}
```

收益：

1. 单客户与群体题可共用一套接口
2. 默认情景与临时 scenario 能统一处理

---

## 阶段三：P1 Composer 重构

### P1-4 把 composer 从硬编码答题器改成受约束生成器

目标：

保留数值正确性约束，但让 LLM 真正负责表达。

改动范围：

1. `orchestrator/composer.py`

具体动作：

1. 新增轻量 `AnswerRenderer` 负责金额、百分比、列表格式化
2. 缩减 `_deterministic_answer()` 的职责
3. 保留 deterministic 的只有：
   - 单位格式
   - 数值格式
   - 缺口为负时的固定结论
4. 其余交给 LLM 基于结构化结果生成

应删除的倾向：

1. 直接把某个 case 常量返回
2. 用 case_tag 决定过多业务表达
3. 把“解释顺序”写死成 if/else

完成标准：

1. 结构化结果正确时，措辞可自然波动
2. 不再依赖硬编码分支覆盖大多数答案

---

## 阶段四：P1 去除 benchmark shortcut

### P1-5 校准数据移出运行时

目标：

把 benchmark 从运行时逻辑迁出。

重点文件：

1. `tools/allocation_engine.py`

具体动作：

1. 删除 runtime 读取 `customer_allocation_metrics.csv`
2. 保留真实配置优化逻辑
3. 在测试中用 benchmark 做对照，不直接注入引擎

完成标准：

1. `min_risk_plan` 来自引擎计算而不是答案表
2. benchmark 只在 tests/eval 中出现

风险说明：

短期内某些题的精确一致率可能下降，但长期泛化和可信度会上升。

---

## 阶段五：P1 Memory 重构

### P1-6 Memory 从 case_tag 续接改为语义续接

当前 memory 更像：

1. customer_id
2. preferences
3. scenario
4. last_case_tag

建议改成：

1. `current_customer_id`
2. `active_preferences`
3. `active_scenario`
4. `last_domain`
5. `last_metric`
6. `last_filters`
7. `last_result_summary`

收益：

1. “那她呢”
2. “默认情况下呢”
3. “那如果按 3% 通胀呢”

这类多轮追问可以基于语义上下文延续，而不是依赖 brittle tag。

---

## 7. 实施顺序建议

建议分两轮推进。

### PR-A：主规划链重构

包含：

1. `SemanticPlan`
2. `PlanValidator` 重写
3. `Planner prompt` 重写
4. `Plan Compiler`
5. `Local planner` 降级

目标：

先解决“LLM 没有真正成为 planner”的根问题。

### PR-B：执行与表达层重构

包含：

1. skill/executor 去题面化
2. composer 收缩 deterministic 逻辑
3. memory 语义化
4. allocation runtime 去 benchmark shortcut

目标：

让工具、记忆和答案生成与新规划链一致。

---

## 8. 测试与评测策略调整

重构后，测试体系也要一起升级。

### 8.1 新测试分层

建议拆成三层：

1. Planner semantic tests
2. Tool execution tests
3. Answer quality tests

### 8.2 Planner semantic tests

验证：

1. 问题是否被映射到正确语义槽位
2. scenario/preferences 是否被正确区分
3. 聚合/过滤是否被正确抽取

而不是验证：

1. 是否命中了某个关键词分支

### 8.3 Tool execution tests

验证：

1. 结构化参数 -> 正确结果
2. SQL/公式/聚合是否准确

### 8.4 Answer quality tests

验证：

1. 是否包含正确数值
2. 是否包含正确结论
3. 是否满足回答风格要求

而不再过度依赖唯一措辞。

---

## 9. 风险与收益

## 9.1 风险

1. 短期内分数可能先波动
2. schema 迁移会牵动 planner、executor、tests
3. 需要更清晰地区分“理解错误”和“执行错误”

## 9.2 收益

1. 同义改写能力显著增强
2. 多轮上下文更稳
3. 新题型扩展不必继续堆关键词
4. LLM 能力真正体现在规划和表达层
5. 系统行为更接近真正的 Agent，而不是规则问答机

---

## 10. 结论

这次重构的关键不是“去掉 JSON”，而是“让 JSON 成为语义计划而不是规则标签”。

中间过程让 LLM 输出 JSON 是对的，但必须满足三个条件：

1. JSON 描述任务语义
2. JSON 成为执行链主事实来源
3. JSON 不再被大规模本地规则覆盖

如果这三点做到，系统才能真正从“规则增强问答”走向“LLM 主导规划的 Agent”。

---

## 11. 下一步建议

建议立刻进入 `PR-A`：

1. 定义 `SemanticPlan`
2. 重写 planner prompt 和 validator
3. 新建 `plan_compiler.py`
4. 把 local planner 降级为真正 fallback

完成 `PR-A` 后，再进入 `PR-B` 做执行层与 composer 的收缩重构。
