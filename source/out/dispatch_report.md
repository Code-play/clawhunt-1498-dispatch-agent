# 派单执行报告（自动生成）

- 任务数：7
- 轨迹条目：23
- 死信：1

## 任务终态

| 任务 | 标题 | 状态 | 执行人 | 重试 | 改派 |
| --- | --- | --- | --- | --- | --- |
| T-1001 | 客户查询接口实现 | DEAD_LETTER | - | 2 | 3 |
| T-1002 | 异步任务队列接入 | ASSIGNED | M-BE-02 | 0 | 0 |
| T-1003 | 订单明细 ETL | DONE | M-DATA-02 | 0 | 1 |
| T-1004 | 生产环境灰度发布 | AWAITING_MANUAL | - | 0 | 1 |
| T-1005 | 审计日志接口补齐 | ASSIGNED | M-BE-01 | 0 | 0 |
| T-1006 | 第三方风控规则接入 | AWAITING_MANUAL | - | 0 | 0 |
| T-1007 | 跨团队协作流程复核 | ASSIGNED | M-QA-01 | 0 | 0 |

## 执行轨迹

| seq | step       | at                   | task   | what                                                                         |
|-----|------------|----------------------|--------|------------------------------------------------------------------------------|
| 1   | dispatch   | 2026-01-05T09:00:00Z | T-1001 | 派单 规则 R-010 → M-BE-01                                                        |
| 2   | dispatch   | 2026-01-05T09:01:30Z | T-1002 | 派单 规则 R-011 → M-BE-02                                                        |
| 3   | dispatch   | 2026-01-05T09:03:00Z | T-1003 | 派单 规则 R-020 → M-DATA-01                                                      |
| 4   | dispatch   | 2026-01-05T09:04:30Z | T-1004 | 派单 规则 R-030 → M-OPS-01                                                       |
| 5   | dispatch   | 2026-01-05T09:06:00Z | T-1005 | 派单 规则 R-010 → M-BE-01                                                        |
| 6   | dispatch   | 2026-01-05T09:07:30Z | T-1006 | 派单 规则 R-999 → 无候选(升级人工)                                                      |
| 7   | escalation | 2026-01-05T09:09:00Z | T-1006 | 无候选，按规则 R-999 执行 security 域升级                                                |
| 8   | dispatch   | 2026-01-05T09:10:30Z | T-1007 | 派单 规则 R-040 → M-QA-01                                                        |
| 9   | recovery   | 2026-01-05T09:12:00Z | T-1001 | timeout: ASSIGNED → RETRYING / retry_with_backoff                            |
| 10  | recovery   | 2026-01-05T09:13:30Z | T-1001 | timeout: RETRYING → RETRYING / retry_with_backoff                            |
| 11  | dispatch   | 2026-01-05T09:15:00Z | T-1001 | 改派 规则 R-010 → M-BE-02                                                        |
| 12  | recovery   | 2026-01-05T09:15:00Z | T-1001 | timeout: RETRYING → REASSIGNED / reassign_next_candidate                     |
| 13  | dispatch   | 2026-01-05T09:16:30Z | T-1001 | 改派 规则 R-010 → M-BE-01                                                        |
| 14  | recovery   | 2026-01-05T09:16:30Z | T-1001 | rejected: REASSIGNED → REASSIGNED / reassign_next_candidate                  |
| 15  | dispatch   | 2026-01-05T09:18:00Z | T-1001 | 改派 规则 R-010 → M-BE-02                                                        |
| 16  | recovery   | 2026-01-05T09:18:00Z | T-1001 | member_unavailable: REASSIGNED → REASSIGNED / reassign_excluding_unavailable |
| 17  | recovery   | 2026-01-05T09:19:30Z | T-1001 | rejected: REASSIGNED → AWAITING_MANUAL / escalate_to_human                   |
| 18  | recovery   | 2026-01-05T09:21:00Z | T-1001 | manual_timeout: AWAITING_MANUAL → DEAD_LETTER / park_in_dead_letter          |
| 19  | dispatch   | 2026-01-05T09:22:30Z | T-1003 | 改派 规则 R-020 → M-DATA-02                                                      |
| 20  | recovery   | 2026-01-05T09:22:30Z | T-1003 | rejected: ASSIGNED → REASSIGNED / reassign_next_candidate                    |
| 21  | recovery   | 2026-01-05T09:24:00Z | T-1003 | completed: REASSIGNED → DONE / release_capacity                              |
| 22  | dispatch   | 2026-01-05T09:25:30Z | T-1004 | 改派 规则 R-030 → 无候选(升级人工)                                                      |
| 23  | recovery   | 2026-01-05T09:25:30Z | T-1004 | member_unavailable: ASSIGNED → AWAITING_MANUAL / escalate_to_human           |

## 死信区

```json
[
  {
    "task_id": "T-1001",
    "title": "客户查询接口实现",
    "reason": "人工接管超时未处理（触发事件 manual_timeout）",
    "retry_count": 2,
    "reassign_count": 3,
    "last_assignee": null,
    "trace": [
      {
        "kind": "timeout",
        "from": "ASSIGNED",
        "to": "RETRYING",
        "action": "retry_with_backoff",
        "detail": "执行人未在 SLA 内受理",
        "at": "2026-01-05T09:12:00Z"
      },
      {
        "kind": "timeout",
        "from": "RETRYING",
        "to": "RETRYING",
        "action": "retry_with_backoff",
        "detail": "第二次超时",
        "at": "2026-01-05T09:13:30Z"
      },
      {
        "kind": "timeout",
        "from": "RETRYING",
        "to": "REASSIGNED",
        "action": "reassign_next_candidate",
        "detail": "第三次超时（重试额度用尽）",
        "at": "2026-01-05T09:15:00Z"
      },
      {
        "kind": "rejected",
        "from": "REASSIGNED",
        "to": "REASSIGNED",
        "action": "reassign_next_candidate",
        "detail": "交付被驳回：缺少接口契约",
        "at": "2026-01-05T09:16:30Z"
      },
      {
        "kind": "member_unavailable",
        "from": "REASSIGNED",
        "to": "REASSIGNED",
        "action": "reassign_excluding_unavailable",
        "detail": "执行人临时请假",
        "at": "2026-01-05T09:18:00Z"
      },
      {
        "kind": "rejected",
        "from": "REASSIGNED",
        "to": "AWAITING_MANUAL",
        "action": "escalate_to_human",
        "detail": "交付再次被驳回",
        "at": "2026-01-05T09:19:30Z"
      },
      {
        "kind": "manual_timeout",
        "from": "AWAITING_MANUAL",
        "to": "DEAD_LETTER",
        "action": "park_in_dead_letter",
        "detail": "人工接管 4h 未处理",
        "at": "2026-01-05T09:21:00Z"
      }
    ],
    "recovery_suggestion": "核对责任域规则表是否缺少可承接该域的成员；补人后从 AWAITING_MANUAL 重新派发。",
    "next_state": "AWAITING_MANUAL",
    "inspectable": true
  }
]
```
