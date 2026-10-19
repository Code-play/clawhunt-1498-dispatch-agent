# 派单 Agent（ClawHunt #1498）

按团队职责分派任务、并回收异常的 Bot。以「**责任域 → 执行人**」规则表驱动派单，
异常用**状态机**描述（超时 / 驳回 / 人员不可用）并给出恢复动作，全程留**执行轨迹**。

- 交付物三样（对应验收标准）：**派单规则示例 · 恢复规则示例 · 执行轨迹示例**
- 环境：Python 3.8+，**仅标准库**（零第三方依赖）；不联网、不调用模型 API、不需要数据库

## 快速开始

```bash
cd 1498-dispatch-agent

# 一键复跑：产出三样样例 + 执行轨迹 + 报告
python -m dispatch_agent demo

# 单元测试（39 个）
python -m unittest discover -s tests -t . -v

# 独立验证（47 条断言，写 verify/verification_record.md 与 verification_result.json）
python verify/run_verification.py

# 只派一个任务，打印决策 JSON（便于用你自己的任务试）
python -m dispatch_agent dispatch \
  --task-json '{"id":"T-X","title":"临时任务","domain":"backend","task_type":"api","priority":4,"required_skills":["api"]}'
```

`demo` 的产物：

| 文件 | 内容 |
|---|---|
| `out/dispatch_trace.jsonl` | 执行轨迹（结构化 JSONL，逐条可核） |
| `out/dead_letters.json` | 死信记录（含恢复建议与下一状态） |
| `out/dispatch_report.md` | Markdown 报告（任务终态 + 轨迹 + 死信） |
| `out/expected_output.txt` | 本次屏幕输出，用于比对复跑是否一致 |

## 目录结构

```
config/team.json              团队花名册（脱敏：只有责任域、技能标签、容量）
config/responsibilities.json  「责任域 → 执行人」规则表（5 条 + 1 条兜底）
config/recovery_policy.json   恢复策略：状态、迁移、额度、不变量
samples/tasks.jsonl           7 条合成任务输入
dispatch_agent/               代码（model / config / dispatch / recovery / trace / cli）
tests/                        39 个单元测试
verify/                       独立验证脚本与验证记录
out/                          demo 产物（可重建，已 gitignore）
```

## 配置说明（改配置即可换团队/换规则，无需改代码）

**规则表** `config/responsibilities.json`，每条规则：

| 字段 | 含义 |
|---|---|
| `priority` | 匹配优先级，从大到小取第一条命中 |
| `when.domain` | 责任域；`"*"` 表示不限 |
| `when.task_type_in` | 任务类型白名单；空数组表示不限 |
| `when.priority_at_least` | 优先级下限；`null` 表示不限 |
| `when.tags_any` | 标签命中任意一个即算命中；空数组表示不限 |
| `assign_to.domain_owner` | 分派到哪个责任域 |
| `assign_to.preferred` | 执行人偏好顺序（只影响打分，不影响资格） |
| `on_no_candidate` | 无可用候选时的动作，默认 `escalate_manual`（转人工） |

候选打分（可解释，逐项写入轨迹）：偏好第 n 位 `40-5×(n-1)` 分；技能命中每项 `+10`；
剩余容量每格 `+5`。责任域不符 / 不可用 / 容量已满的成员直接排除。

**恢复策略** `config/recovery_policy.json`：`states` 定义状态，`transitions` 定义
「事件 → 允许的当前状态 → 目标状态 + 恢复动作」，`limits` 定义额度
（`max_retries` / `max_reassigns` / `backoff_seconds` / `manual_sla_hours`）。
新增一种异常：在 `transitions` 里加一条，代码无需改动；策略自洽性在加载时校验。

## 异常处置一览

| 事件 | 额度内 | 额度用尽 |
|---|---|---|
| `timeout` | `RETRYING` + 退避重试（30s、120s） | `REASSIGNED` 改派下一候选 |
| `rejected` | `REASSIGNED` 改派下一候选 | `AWAITING_MANUAL` 转人工（SLA 4h） |
| `member_unavailable` | `REASSIGNED` 改派（排除不可用者） | `AWAITING_MANUAL` 转人工 |

`AWAITING_MANUAL` 超过 SLA 未处理 → `DEAD_LETTER`（死信区），记录含任务、原因、
重试/改派次数、完整轨迹、恢复建议与**明确的下一状态**。任务在任何路径下都不会静默消失。

## 常见问题

**Q：为什么配置用 JSON 而不是 YAML？**
A：为了「一键复跑」零依赖。YAML 需要 PyYAML（第三方包），JSON 是标准库。

**Q：任务会不会因为没人可用就丢了？**
A：不会。派单阶段无候选 → 按规则升级人工；异常阶段额度用尽 → 转人工；人工超时 → 死信区。
三条路径都有断言覆盖（见 `verify/verification_record.md`）。

**Q：输出可复现吗？**
A：可。时间来自确定性时钟（固定起点 + 90s 步长），连续两次 `demo` 的
`dispatch_trace.jsonl` 与 `expected_output.txt` **逐字节一致**（验证脚本会断言）。

**Q：中文输出乱码？**
A：若用 `conda run`，conda 会用自己的 GBK 编码重新打印子进程输出，含中文时会报
`UnicodeEncodeError` 且退出码 1。**直接用 python 运行**；必须用 conda run 时先设
`PYTHONIOENCODING=utf-8`。这是 conda 的输出重编码问题，不是本工具的问题。

**Q：怎么接真实团队？**
A：把 `config/team.json` 换成真实花名册（脱敏即可，只需 id/责任域/技能/容量），
把 `config/responsibilities.json` 换成你们的责任域规则。代码不用改。

## 边界

不依赖系列其它单的交付物；不接真实账号与权限；只用脱敏或合成数据；
模型 API、云资源、训练算力不在本单范围内（本工具也不需要）。
