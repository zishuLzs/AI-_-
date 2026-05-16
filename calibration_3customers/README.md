# Calibration Dump

- Generated at: 2026-05-16T17:23:52
- Customer count: 3
- Backend: mysql
- Base table: train_base_table
- Action table: train_action_table

## Files
- `customer_profiles.csv`: base_table profiles plus monthly saving and age bucket.
- `customer_behavior_summary.csv`: one row per customer, top product and behavior counts.
- `customer_behavior_long.csv`: one row per customer-product behavior group.
- `customer_retirement_metrics.csv`: per-customer retirement outputs under multiple scenarios.
- `customer_product_projections.csv`: per-customer projected retirement assets by allowed product.
- `customer_allocation_metrics.csv`: max-return and min-risk plan summaries (unless skipped).
- `aggregate_summary.json`: global aggregates useful for expected-value calibration.

## Notes
- Default retirement scenario uses the long-term goal `消费水平不下降`.
- `goal_monthly_12000` and `goal_monthly_15000` are generic scenario surfaces for QA expansion.
- Allocation output can be relatively slow on larger dumps; use `--skip-allocation` if needed.