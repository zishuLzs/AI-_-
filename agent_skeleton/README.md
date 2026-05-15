# 养老规划 Agent 技术实现骨架

这是基于 [任务2_养老规划Agent建设_实现方案.md](/Users/lzs/Desktop/个人资料/求职/招行数字金融训练营/ai数据科学家/任务2_养老规划Agent建设_实现方案.md) 搭建的一套 Python 代码骨架，目标是提供一个可运行、可扩展、便于继续补全比赛逻辑的最小工程。

## 目录说明

```text
agent_skeleton/
├─ app.py
├─ init_db.py
├─ models.py
├─ config/
│  ├─ __init__.py
│  └─ settings.py
├─ skills/
│  ├─ __init__.py
│  ├─ allocation_planning.py
│  ├─ behavior_analysis.py
│  ├─ customer_profile.py
│  ├─ proposal_writer.py
│  └─ retirement_calc.py
├─ tools/
│  ├─ __init__.py
│  ├─ allocation_engine.py
│  ├─ formula_engine.py
│  ├─ memory_manager.py
│  ├─ router.py
│  ├─ sql_executor.py
│  └─ sql_templates.py
└─ tests/
   ├─ test_formula.py
   ├─ test_memory.py
   └─ test_router.py
```

## 运行方式

### 1. 准备数据库

将比赛数据 CSV 放到任意位置，然后执行：

```bash
python init_db.py --base /path/to/base_table.csv --action /path/to/action_table.csv --db ./pension_agent.db
```

默认会创建 SQLite 数据库，并建立基础索引。

### 2. 启动交互式 Agent

```bash
python app.py --db ./pension_agent.db
```

示例提问：

```text
客户 V500001 现在年龄多大？
客户 V500001 距离退休还有多久？
客户 V500001 想要退休后消费水平不下降，在他刚退休时，每月需要支出多少钱？
为客户 V500001 生成一份养老规划建议书
```

### 3. 运行测试

```bash
python -m unittest discover -s tests
```

## 当前骨架已支持

1. 规则路由和客户 ID 提取。
2. 多轮会话内存。
3. “假设”与“观点”分离存储。
4. 模板 SQL 查询。
5. 养老核心公式计算。
6. 基于规则和枚举的资产配置。
7. 建议书生成。

## 后续建议补强

1. 将 SQLite 替换为 DuckDB，以适配更大规模分析型查询。
2. 根据真实字段名对 `init_db.py` 做一次校准。
3. 扩展 `router.py` 的意图分类，接入大模型兜底。
4. 补充更多 SQL 模板，覆盖群体统计、行为过滤、复杂聚合。
5. 用真实样例数据回归校验 Q1-Q8 和建议书题型。
