# Autoresearch Program: 养老规划 Agent 代码优化

## Objective

Maximize a weighted compliance score against the task2 requirements (README.md + 任务2_养老规划Agent建设.md).

## Primary Metric

`total_score` from `scorer.py` — a weighted composite of 8 dimensions:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| 提交协议合规 | 15% | CLI入口、环境变量、并行安全、requirements.txt |
| 意图路由准确率 | 15% | 各类问题的正确路由、群体统计支持 |
| 假设/观点隔离 | 10% | 从句级假设/观点分离、多轮记忆正确性 |
| 数值计算精度 | 10% | Q1-Q8 数值正确、取整规则 |
| 建议书质量 | 20% | LLM润色、结构化完整性、关注点汇总 |
| 资产配置质量 | 10% | 风险约束、生命周期约束、年金纳入 |
| 工程健壮性 | 10% | 类型安全、None安全、错误处理 |
| SQL正确性 | 10% | 字段名正确、非财富过滤、产品映射准确性 |

## Edit Surface

Only `agent_skeleton/` directory.
- No new dependencies beyond pymysql + requests.
- No breaking changes to the `run(inf: str) -> str` interface.

## Keep/Discard Rules

- **Keep**: total_score increases, OR a dimension scoring 0 improves to >0.
- **Discard**: total_score drops, OR a critical regression (existing dimension score drops by >20%).
- **Revert strategy**: `git checkout -- <file>` if discard.

## Experiment Budget

Maximum 10 iterations unless score converges to >95.
