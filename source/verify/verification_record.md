# 验证记录 · 派单 Agent（订单 #1498）

生成时间（UTC）：2026-10-19T03:23:02.688991+00:00
复跑命令：`python verify/run_verification.py`

## 1. 配置加载与校验

- 团队 6 人；规则 5 条 + 兜底 1 条；状态 6 个

## 2. 派单规则（责任域 → 执行人）

- 逐任务命中与候选排序均已给出（7 条决策）
- 无候选升级：['T-1006']

## 3. 恢复规则（异常状态机）

- 覆盖：超时退避 / 重试用尽改派 / 驳回用尽转人工 / 人员不可用（有替代·无替代）/ 人工超时进死信 / 完成释放容量
- 回归断言：改派必须释放原执行人容量（否则容量单调泄漏导致误升级）

## 4. 执行轨迹


## 5. 一键复跑确定性


## 6. 单元测试

```
----------------------------------------------------------------------
Ran 39 tests in 0.029s

OK
```

## 结论

- 断言总数：47；通过：47；失败：0
- 结果：**全部通过**

| 断言 | 预期 | 实际 | 结果 |
|---|---|---|---|
| 团队花名册加载 | >=4 人 | 6 | 通过 |
| 规则表加载 | >=3 条 | 5 | 通过 |
| 规则按优先级降序 | 降序 | [100, 90, 80, 70, 60] | 通过 |
| 兜底规则存在 | True | True | 通过 |
| 恢复策略含全部状态 | >=5 个 | 6 | 通过 |
| 恢复策略含额度限制 | max_retries/max_reassigns/manual_sla_hours | manual_sla_hours,max_reassigns,max_retries | 通过 |
| T-1001 命中规则 | True | True | 通过 |
| T-1001 判定可解释 | True | True | 通过 |
| T-1002 命中规则 | True | True | 通过 |
| T-1002 判定可解释 | True | True | 通过 |
| T-1003 命中规则 | True | True | 通过 |
| T-1003 判定可解释 | True | True | 通过 |
| T-1004 命中规则 | True | True | 通过 |
| T-1004 判定可解释 | True | True | 通过 |
| T-1005 命中规则 | True | True | 通过 |
| T-1005 判定可解释 | True | True | 通过 |
| T-1006 命中规则 | True | True | 通过 |
| T-1006 判定可解释 | True | True | 通过 |
| T-1007 命中规则 | True | True | 通过 |
| T-1007 判定可解释 | True | True | 通过 |
| 无匹配任务走兜底规则 | R-999 | R-999 | 通过 |
| 无候选任务被升级而非丢弃 | T-1006 | T-1006 | 通过 |
| 技能命中压过偏好位次 | M-BE-02 第一 | M-BE-02 | 通过 |
| 候选排序给出理由 | True | True | 通过 |
| 容量满后轮到下一人 | M-DATA-02 | M-DATA-02 | 通过 |
| 超时→退避重试 | retry_with_backoff | retry_with_backoff | 通过 |
| 退避第一档 30s | 30 | 30 | 通过 |
| 退避第二档 120s | 120 | 120 | 通过 |
| 重试额度用尽→改派 | REASSIGNED | REASSIGNED | 通过 |
| 回归：改派释放原执行人容量 | 0 | 0 | 通过 |
| 驳回额度用尽→转人工 | AWAITING_MANUAL | AWAITING_MANUAL | 通过 |
| 转人工带 SLA | 4 | 4 | 通过 |
| 人工超时→死信区 | DEAD_LETTER | DEAD_LETTER | 通过 |
| 死信记录可检查 | True | True | 通过 |
| 死信记录字段齐全 | task_id,reason,retry_count,reassign_count,trace,recovery_suggestion,next_state | task_id,reason,retry_count,reassign_count,trace,recovery_suggestion,next_state | 通过 |
| 不可用且有替代→改派 | REASSIGNED | REASSIGNED | 通过 |
| 不可用且无替代→转人工 | AWAITING_MANUAL | AWAITING_MANUAL | 通过 |
| 未定义事件抛错（不静默吞掉） | RecoveryError | RecoveryError | 通过 |
| 完成→DONE 并释放容量 | DONE/0 | DONE/0 | 通过 |
| 轨迹为可解析 JSONL | 2 | 2 | 通过 |
| seq 连续 | [1,2] | [1, 2] | 通过 |
| 时间戳单调不减 | 非递减 | 2026-01-05T09:00:00Z,2026-01-05T09:01:30Z | 通过 |
| demo 轨迹时间戳单调不减 | 非递减 | 23 条 | 通过 |
| demo 轨迹含三类步骤 | dispatch/escalation/recovery | dispatch,escalation,recovery | 通过 |
| demo 复跑退出码 | 0 | 0 | 通过 |
| 两次运行产物逐字节一致 | 哈希相同 | dispatch_trace.jsonl:同,expected_output.txt:同 | 通过 |
| 单元测试全部通过 | returncode 0 | 0 | 通过 |