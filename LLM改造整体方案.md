# 任务2 养老规划 Agent LLM 改造整体方案

## 1. 文档目标

本文档用于说明：在当前 `agent_skeleton/` 已具备 SQL 查询、公式计算、资产配置和建议书模板生成能力的基础上，如何将现有 `纯规则 / 模板驱动` 的自然语言理解与内容生成方案，升级为 `LLM 主导理解与编排 + 工具约束执行` 的 Agent 架构。

这里特别强调一条改造原则：

`不要用规则兜底来掩盖 LLM 的真实问题。`

也就是说，改造目标不是“保留一条规则快路径，把 LLM 当装饰”，而是：

1. 让 LLM 真正负责复杂自然语言理解、上下文整合、开放式生成。
2. 让 SQL、公式、产品映射、配置求解继续由确定性工具执行。
3. 在 LLM 规划失败、输出不合法、工具参数不完整时，显式暴露失败并返回可诊断结果，而不是悄悄退回规则系统。

本方案本质上是一套 `LLM-first, Tool-constrained, Failure-visible` 的改造设计。

---

## 2. 当前项目要求与外部约束调研

## 2.1 提交与运行约束

根据 [任务2/README.md](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/README.md:3)，提交程序必须满足：

1. 提供 `run.py`
2. 支持命令行调用：

```bash
python3 run.py "客户V500001现在年龄多大？"
```

3. 标准输出只能返回最终答案
4. 支持并行调用
5. 不依赖共享可变文件状态

这意味着 LLM 改造后的系统必须仍然保持：

1. `run(inf: str) -> str`
2. 命令行直接执行
3. 不输出调试过程

## 2.2 数据库约束

根据 [任务2/README.md](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/README.md:62)，数据库访问必须满足：

1. 使用 MySQL
2. 连接参数从环境变量读取
3. 表名从环境变量读取
4. 严禁把全量数据拉到本地
5. 分析必须依赖 SQL 查询或聚合

当前项目已经在 [tools/sql_executor.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/sql_executor.py:20) 中具备基本能力，可作为 LLM 改造后的工具执行层。

## 2.3 LLM 接入约束

根据 [任务2/README.md](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/README.md:160) 与 [llm_call_example.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/llm_call_example.py:4)，LLM 调用需遵守：

1. `ONE_API_URL` 必须从环境变量读取
2. `ONE_API_KEY` 从平台说明获取
3. 可用模型：
   - `doubao-seed-2-0-lite-260428-cmb`
   - `qwen3.6-flash`
4. 平台会统计 Token 消耗

这意味着：

1. LLM 调用必须可控
2. Prompt 必须短
3. 输出必须结构化
4. 不允许把整个任务说明、完整对话历史、全量中间结果反复灌进模型

## 2.4 题目核心评分约束

根据 [任务2_养老规划Agent建设.md](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/任务2_养老规划Agent建设.md:107)，系统必须满足：

1. 正确识别问题并调用对应能力
2. 通过 SQL 访问数据库
3. 数值计算误差控制在 `0.1%`
4. 行为偏好必须映射到标准产品库
5. 支持历史会话记忆，且区分 `假设` 与 `观点`
6. 兼顾正确率、耗时与 Token

所以 LLM 改造的边界非常清晰：

`LLM 负责理解、规划、组织；程序负责取数、计算、验证。`

---

## 3. 当前项目现状调研

当前 `agent_skeleton/` 已经具备下列模块：

1. 入口与会话编排：
   - [run.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/run.py:1)
2. SQL 执行层：
   - [tools/sql_executor.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/sql_executor.py:1)
   - [tools/sql_templates.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/sql_templates.py:1)
3. 会话记忆：
   - [tools/memory_manager.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/memory_manager.py:1)
4. 当前规则路由：
   - [tools/router.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/router.py:1)
5. 公式与测算：
   - [tools/formula_engine.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/formula_engine.py:1)
6. 资产配置：
   - [tools/allocation_engine.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/allocation_engine.py:1)
7. Skill 层：
   - `customer_profile`
   - `behavior_analysis`
   - `retirement_calc`
   - `allocation_planning`
   - `proposal_writer`

当前规则方案的问题不是“完全不能用”，而是：

1. 路由仍然严重依赖关键词
2. 参数抽取依赖正则和子句切分
3. 混合表达、多轮追问、自然改写问法上限明显
4. 建议书虽然可生成，但个性化与表达质量受限
5. 规则越来越多后，系统会进入“看起来稳，实则靠大量 hardcode 勉强覆盖”的状态

所以本次改造的核心不是继续给规则打补丁，而是：

`把自然语言理解主权交给 LLM，把工具执行权留给程序。`

---

## 4. 改造总原则

## 4.1 LLM 主导，不以规则兜底

这是本方案与之前版本最大的不同。

新原则是：

1. 默认由 LLM planner 负责意图识别、参数抽取、工具规划。
2. 规则模块不再承担业务兜底职责。
3. 如果 LLM 输出失败、字段缺失、schema 非法，应显式报错或返回受控失败答案，而不是偷偷改走规则路径。

原因很明确：

1. 规则兜底会掩盖 LLM 真实弱点。
2. 你会误以为“LLM 改造成功”，其实只是规则路径在默默接盘。
3. 最终很难判断质量来自模型还是来自旧系统残留。

### 4.1.1 不允许“伪兜底”

除了显式的规则 fallback，还要禁止几类常见的“伪兜底”做法：

1. `planner` 没抽出 `customer_id` 时，程序再用正则偷偷补抽。
2. `planner` 意图不明确时，程序再用关键词表强行改判成某个 intent。
3. `planner` 没给出完整参数时，程序凭经验脑补默认业务含义。
4. 建议书生成失败时，程序回退到旧模板直接拼装出看似正常的答案。

这些做法虽然表面上“不叫规则兜底”，本质上仍然是在隐藏 LLM 问题，因此提交主流程中一律禁止。

### 4.1.2 规则模块的新定位

当前 [tools/router.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/router.py:1) 不再作为运行时 fallback，而改为：

1. 开发期对照基线
2. 回归测试基线
3. 离线对比器

换句话说：`保留代码，不参与提交版主流程。`

### 4.1.3 允许的仅是“格式规范化”，不是“语义修复”

可以保留的程序侧处理只有确定性的格式规范化，例如：

1. 把 `"73%"` 规范成 `0.73`
2. 把 `"3%"` 规范成 `0.03`
3. 把工具名做大小写标准化

这些处理不改变语义，只是把已明确表达的值转换成内部表示。

但以下行为不允许：

1. 把“养老差多少”自动猜成“养老金缺口测算”
2. 把“稳一点”自动改写成某个固定配置策略
3. 把未提到客户 ID 的问题自动继承为上一个客户，除非会话记忆中当前客户已被明确锁定且 planner 明确引用

## 4.2 工具优先，模型编排

LLM 不能直接负责：

1. SQL 最终执行
2. 数值计算
3. 产品映射
4. 配置结果最终数值

LLM 只负责：

1. 意图识别
2. 参数抽取
3. 会话语义整理
4. 工具调用规划
5. 最终语言组织

## 4.3 失败可见，不要静默修复

改造后系统必须具备：

1. LLM 输出 schema 校验
2. 工具参数合法性校验
3. 工具执行失败显式上抛
4. 失败分类记录

如果 planner 输出：

1. 缺少 customer_id
2. 意图不在枚举内
3. scenario / preferences 混淆
4. tool_call 参数不完整

系统应该：

1. 标记本次失败类型
2. 返回受控的最短错误响应
3. 在本地日志中记录结构化失败原因

而不是回退到规则系统继续“看起来答对”。

## 4.4 LLM 输出必须结构化

所有关键 LLM 调用都必须输出 JSON。

不允许：

1. 让 LLM 直接自由发挥写完整答案再解析
2. 让 LLM 直接写 SQL
3. 让 LLM 直接“脑补”客户数据和金额

---

## 5. 推荐的新总体架构

改造后的总体结构如下：

```text
run.py
  ↓
Conversation Orchestrator
  ↓
LLM Planner
  ↓
Structured Plan(JSON)
  ↓
Plan Validator
  ↓
Tool Executor
  ├─ SQL Tool
  ├─ Behavior Tool
  ├─ Formula Tool
  ├─ Allocation Tool
  └─ Memory Tool
  ↓
Structured Result Bundle
  ↓
LLM Composer
  ↓
Final Answer
```

注意：这里没有 `Rule Fallback Path`。

### 5.1 新增模块建议

建议新增：

```text
agent_skeleton/
├─ llm/
│  ├─ __init__.py
│  ├─ client.py
│  ├─ prompts.py
│  ├─ schemas.py
│  └─ validator.py
├─ orchestrator/
│  ├─ __init__.py
│  ├─ planner.py
│  ├─ executor.py
│  ├─ composer.py
│  └─ failures.py
```

### 5.2 保留模块

以下模块保留并作为确定性执行层：

1. [tools/sql_executor.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/sql_executor.py:1)
2. [tools/sql_templates.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/sql_templates.py:1)
3. [tools/formula_engine.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/formula_engine.py:1)
4. [tools/allocation_engine.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/allocation_engine.py:1)
5. [tools/memory_manager.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/memory_manager.py:1)

---

## 6. 具体改造方案

## 6.1 第一层：用 LLM 全面替换运行时路由与参数抽取

### 当前问题

当前 `IntentRouter` 通过：

1. 关键词匹配
2. 正则抽金额
3. 子句切分做 scenario / preferences 划分

它的问题不在于“逻辑错误”，而在于泛化上限低。

### 改造方案

新增 `LLMPlanner`，让其输出固定 JSON：

```json
{
  "intent": "retirement",
  "customer_id": "V500002",
  "memory_update": {
    "preferences": {
      "retirement_goal": "消费水平不下降"
    },
    "scenario": {
      "inflation_annual": 0.03
    }
  },
  "tool_calls": [
    {
      "name": "get_profile",
      "params": {
        "customer_id": "V500002"
      }
    },
    {
      "name": "calculate_retirement",
      "params": {
        "customer_id": "V500002"
      }
    }
  ],
  "answer_mode": "short"
}
```

### 核心要求

1. LLM 必须输出严格 schema。
2. Planner 输出失败时，不允许走规则 fallback。
3. Planner 输出非法时，返回受控失败结果，例如：

`抱歉，当前问题解析失败，请重新表述。`

同时在本地日志里记录：

1. 原问题
2. 原始模型输出
3. schema 校验失败原因

### 可接受的恢复方式

允许的恢复方式只有一种：

1. 对同一个 LLM 结果做一次 `repair prompt` 重试，要求它修正为合法 JSON。

但这次重试仍然属于 `LLM 自修复`，不是本地规则接管。若修复后仍失败，则直接失败，不再进入任何关键词路由、正则补参或模板兜底。

### Prompt 设计原则

Prompt 必须短小，只给：

1. 当前问题
2. 当前会话摘要
3. 可选 intent 枚举
4. memory 字段定义
5. tool_call schema

禁止把整份题面和所有业务规则都塞入 planner prompt。

---

## 6.2 第二层：LLM 不能直接写 SQL，只能写工具计划

### 原则

LLM 不生成可执行 SQL，而是生成工具调用意图。

例如：

```json
{
  "tool_calls": [
    {
      "name": "behavior_aggregate",
      "params": {
        "metric": "avg_age",
        "product": "权益类产品",
        "action_type": "浏览",
        "min_count": 2
      }
    }
  ]
}
```

再由程序映射成 SQL 模板。

### 为什么不能让 LLM 直接写 SQL

1. 容易字段名漂移
2. 容易产生非法 SQL
3. 容易引入 SQL 幻觉
4. 调试困难
5. Token 变高

### 推荐实现

由工具执行层维护白名单工具：

1. `get_profile`
2. `count_customers`
3. `avg_customers`
4. `analyze_behavior_single`
5. `analyze_behavior_aggregate`
6. `calculate_retirement`
7. `build_allocation`
8. `generate_proposal_payload`

LLM 只能从这些工具中选，不能发明新工具。

同时每个工具参数也必须是枚举或受限结构，例如：

1. `metric` 只能来自预定义集合
2. `product` 只能来自产品库标准名称
3. `action_type` 只能来自系统定义动作集合
4. `answer_mode` 只能是 `short / normal / proposal`

这样可以避免把“自由文本歧义”继续带进执行层。

---

## 6.3 第三层：保留会话记忆，但由 LLM 决定写什么，由程序决定能不能写

### 目标

LLM 负责识别：

1. 哪些是长期观点
2. 哪些是本轮假设
3. 哪些只是提问背景

程序负责仲裁：

1. customer_id 是否变化
2. scenario 是否只本轮生效
3. 非法字段是否丢弃

### 会话记忆建议结构

```json
{
  "customer_id": "V500002",
  "preferences": {
    "retirement_goal": "消费水平不下降",
    "focus_points": ["流动性", "长寿风险"]
  },
  "scenario": {
    "inflation_annual": 0.03
  },
  "conversation_summary": [
    "客户明确希望退休后生活水平不下降",
    "客户关注流动性和长寿风险"
  ]
}
```

### 特别约束

1. `scenario` 不能进入长期记忆
2. 切换客户必须清空旧客户上下文
3. LLM 输出的 memory 字段必须经过白名单校验
4. 如果 planner 没有明确写入观点，程序不能自己从原问句二次抽取并写入记忆

---

## 6.4 第四层：建议书生成改为 LLM 主导，但只消费结构化事实

### 当前问题

当前建议书更多是模板拼装，表达上限不高。

### 改造方案

建议书生成分两步：

#### 第一步：程序生成结构化 payload

由工具层输出：

```json
{
  "profile": {...},
  "assumptions": {...},
  "preferences": {...},
  "behavior_summary": {...},
  "retirement_result": {...},
  "allocation_plan": {...}
}
```

#### 第二步：LLM 生成完整建议书

LLM 只负责把这些结构化数据组织成 7 个章节：

1. 基本情况
2. 基本假设
3. 养老目标
4. 退休后财富需求测算
5. 产品偏好
6. 资产配置方式与具体方案
7. 其他建议

### Prompt 要求

Prompt 必须强调：

1. 只能使用给定 payload
2. 禁止改写数值、比例、客户画像
3. 必须汇总前序提问中的关注点
4. 必须区分系统默认假设、客户观点和本轮临时假设

### 建议书失败策略

如果 LLM 建议书输出：

1. 不符合章节结构
2. 丢失关键数值
3. 数字与 payload 不一致

则本轮建议书直接判定失败并返回受控错误，不走模板 fallback。

因为本方案的目标是暴露 LLM 真实问题，而不是隐藏问题。

---

## 6.5 第五层：普通问答采用 LLM Composer，但限定短答

### 普通问答的思路

普通问答仍然先由工具得到结构化结果，再交给 LLM Composer 生成短答。

例如输入：

```json
{
  "question": "客户 V500003 距离退休还有多久？",
  "intent": "retirement",
  "tool_result": {
    "retirement_duration_text": "12年7个月"
  }
}
```

LLM 输出：

`12年7个月`

### 约束

1. 回答长度严格受控
2. 不补充题面未要求的解释
3. 数值类题尽量保持简洁

### 为什么普通问答也要让 LLM 参与

因为这才是真正的 LLM 改造：

1. 不是只让 LLM 写建议书
2. 而是让它接管整体自然语言层

但为了控成本，普通问答的 composer prompt 必须极短。

---

## 7. 不采用规则兜底后的失败处理策略

既然不用规则兜底，就必须有一套明确的失败处理框架。

这里再强调一次：

`失败处理 = 显式失败 + 记录原因，不等于偷偷改走旧逻辑。`

## 7.1 失败类型

建议定义以下失败类别：

1. `planner_schema_error`
2. `planner_missing_customer_id`
3. `planner_invalid_tool`
4. `planner_invalid_memory_update`
5. `tool_execution_error`
6. `composer_schema_error`
7. `proposal_consistency_error`

## 7.2 对用户输出

为了符合标准输出要求，失败时只返回最短受控答案，例如：

1. `抱歉，当前问题解析失败，请重新表述。`
2. `抱歉，当前问题所需信息不完整。`
3. `抱歉，当前建议书生成失败。`

不要输出 traceback，不要输出 JSON，不要输出 planner 中间结果。

## 7.2.1 失败分层策略

为避免“失败即崩溃”过于粗糙，建议采用以下分层：

1. `planner` 首次输出非法：触发一次 LLM repair
2. `planner` repair 后仍非法：直接失败
3. 工具参数校验失败：直接失败
4. 工具执行失败：直接失败
5. `composer` 输出不符合约束：普通问答可退化为程序短答，建议书直接失败

这里的“普通问答退化为程序短答”不属于规则兜底，因为它不是旧路由或旧模板接管，而是对已经正确执行出的结构化结果做最小文本化，例如：

- 输入：`{"answer_text": "12年7个月"}`
- 输出：`12年7个月`

也就是说，退化发生在“表达层”，不发生在“理解层”和“规划层”。

## 7.3 对本地日志输出

日志写到唯一文件名，例如：

`logs/run_{pid}_{time_ms}.log`

记录：

1. 原问题
2. 当前会话摘要
3. LLM 原始输出
4. 校验失败原因
5. 工具执行参数

这样既不污染标准输出，也能暴露真实问题。

---

## 8. 推荐的模型调用分工

为了兼顾质量和 Token，推荐只保留两个 LLM 调用点：

## 8.1 Planner Model

职责：

1. 意图识别
2. 参数抽取
3. memory_update 识别
4. tool_calls 规划

建议模型：

1. `qwen3.6-flash`

特点：

1. 速度快
2. Token 低
3. 适合结构化 JSON 输出

## 8.2 Composer Model

职责：

1. 普通问答短答
2. 建议书成文

建议模型：

1. `qwen3.6-flash` 作为默认
2. `doubao-seed-2-0-lite-260428-cmb` 作为建议书质量对比实验模型

### 为什么不增加第三个模型角色

因为比赛里：

1. 调用点越多，Token 越高
2. 系统越复杂，失败面越大

两个角色已经足够。

---

## 9. 具体改造计划

## 第一阶段：移除运行时规则路由，建立 LLM Planner

目标：

1. 新增 `llm/client.py`
2. 新增 `llm/schemas.py`
3. 新增 `orchestrator/planner.py`
4. 让 `run.py` 主流程先调用 planner，而不是当前 `IntentRouter`

验收标准：

1. 所有现有示例题都能产出合法 plan
2. 不使用规则 fallback
3. planner 输出失败时能显式暴露
4. [tools/router.py](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2/agent_skeleton/tools/router.py:1) 不再出现在 `run.py` 主链路中

## 第二阶段：建立 Tool Executor 与 Plan Validator

目标：

1. 解析 planner 输出的 `tool_calls`
2. 映射到现有 `skills/` 或 `tools/`
3. 对 customer_id、memory_update、scenario、tool params 做校验

验收标准：

1. 所有工具调用都走白名单
2. 不允许自由 SQL
3. 失败路径可诊断

## 第三阶段：建立 LLM Composer

目标：

1. 普通问答统一走 composer
2. 建议书走 proposal composer
3. 输出风格稳定、长度可控

验收标准：

1. 普通问答不冗长
2. 建议书结构完整
3. 数值不漂移

## 第四阶段：压测与提示词收敛

目标：

1. 统计平均耗时
2. 统计平均 Token
3. 统计 planner / composer 失败率
4. 用评测样例回放迭代 prompt

验收标准：

1. 在质量提升的同时，Token 不失控
2. 失败率可控

## 第五阶段：提交版收口

目标：

1. 清理未使用的运行时规则入口
2. 确保提交目录根下 `run.py` 只走新主链路
3. 检查 stdout 不泄露调试信息
4. 检查并行运行不共享可变状态

验收标准：

1. 提交版不存在“planner 失败 -> router 接管”之类隐藏分支
2. 建议书链路不存在“composer 失败 -> 旧模板接管”之类隐藏分支
3. 所有环境变量读取方式符合题目要求

---

## 10. 风险与应对

## 10.1 风险一：没有规则兜底后，首版失败率会更高

这是预期现象，不是坏事。

因为本方案本来就要求：

1. 先暴露真实问题
2. 再通过 prompt / schema / 工具设计修掉问题

而不是继续靠规则遮丑。

## 10.2 风险二：LLM 输出结构化 JSON 不稳定

应对：

1. 缩短 prompt
2. 使用极严格 schema
3. 限制输出字段
4. 做 JSON parse + schema validate

## 10.3 风险三：建议书 Token 太高

应对：

1. 只传结构化 payload，不传整段历史
2. 只保留 7 个必需章节
3. 温度降低
4. 用短 prompt 指定禁止空话

## 10.4 风险四：planner 把假设和观点分错

应对：

1. memory_update 必须经过程序白名单校验
2. 增加混合表达专项测试
3. 加强 prompt 中关于 `如果 / 假设 / 假如` 与 `想要 / 希望 / 认为` 的定义

---

## 11. 最终推荐结论

如果目标是彻底突破当前“纯规则/模板方案的自然语言上限”，推荐的方向不是：

1. 继续给规则打补丁
2. 保留规则当运行时兜底

而是：

`用 LLM 全面接管自然语言理解与生成主流程，用工具层约束事实查询与数值执行，用结构化校验和显式失败机制替代规则兜底。`

更具体地说，推荐的最终形态是：

1. `LLM Planner` 负责理解问题、拆出意图、观点、假设、工具计划
2. `Tool Executor` 负责 SQL、公式、配置和会话写入
3. `LLM Composer` 负责短答与建议书
4. `Validator + Failure Handler` 负责暴露问题，而不是掩盖问题

因此，本次改造的最终结论是：

`将当前项目改造成一个 LLM-first 的养老规划 Agent，而不是“规则主导、LLM 点缀”的系统。`
