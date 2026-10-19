# 验收对照（订单 #1498 · 派单 Agent）

订单范围：配置按团队职责分派任务与异常回收的 Bot。
验收标准（原文）：`Provides examples of dispatch rules, recovery rules, and execution traces.`

| 验收要求 | 交付物 | 复跑与核验方式 |
|---|---|---|
| **派单规则示例**（dispatch rules） | `config/responsibilities.json`（5 条规则 + 1 条兜底）；`dispatch_agent/dispatch.py` 的匹配与打分 | `python -m dispatch_agent demo` 第 1 节：逐任务打印命中规则、判定理由、候选排序（含分数构成）；`out/dispatch_trace.jsonl` 中 12 条 `dispatch` 记录 |
| **恢复规则示例**（recovery rules） | `config/recovery_policy.json`（6 种事件 × 迁移 + 额度 + 3 条不变量）；`dispatch_agent/recovery.py` | `demo` 第 2 节：实测覆盖超时退避（30s→120s）、重试用尽改派、驳回用尽转人工（SLA 4h）、人员不可用（有替代/无替代）、人工超时进死信、完成释放容量；`out/dispatch_trace.jsonl` 中 10 条 `recovery` 记录 |
| **执行轨迹示例**（execution traces） | `dispatch_agent/trace.py`；产物 `out/dispatch_trace.jsonl`（23 条）+ `out/dispatch_report.md` + `out/dead_letters.json` | 轨迹含 seq/时间/任务/规则或迁移/可读理由；demo 第 3 节打印人可读表格；JSONL 可逐条解析核对 |
| 交付要求：代码或配置 | 19 个源码/配置文件（`dispatch_agent/`、`config/`、`samples/`、`tests/`、`verify/`）+ 4 个 demo 产物（`out/`） | 见 `SOLUTION.md` 的交付物清单 |
| 交付要求：使用说明 | `README.md` | 含环境、安装、一键复跑、配置说明、异常处置一览、常见问题 |
| 交付要求：验证记录 | `verify/run_verification.py` + `verification_record.md` + `verification_result.json` | `python verify/run_verification.py` → **47/47 断言通过**（退出码 0） |
| 只用获授权或脱敏资料 | `config/team.json`（无姓名/账号，只有责任域与容量）、`samples/tasks.jsonl`（合成任务） | 团队花名册与任务输入均为脱敏/合成；验证不依赖任何真实数据 |
| 不依赖其它单（买家助手问题 1） | 自包含包，无外部服务、无数据库、无模型 API | 断网可跑：`python -m dispatch_agent demo` |
| 脱敏数据范围（买家助手问题 2） | 验证场景全部由合成数据构造 | 真实团队接入只需替换 `team.json` 与 `responsibilities.json` |

## 验证结果

| 项目 | 结果 |
|---|---|
| 单元测试 | **39 / 39 通过**（`python -m unittest discover -s tests -t .`） |
| 验证断言 | **47 / 47 通过**（`python verify/run_verification.py`，退出码 0） |
| 一键复跑确定性 | 连续两次 `demo` 的 `dispatch_trace.jsonl` 与 `expected_output.txt` **逐字节一致** |
| 任务丢失 | 7 条任务终态全部有名字（DEAD_LETTER / AWAITING_MANUAL / ASSIGNED / DONE），**无静默丢弃** |

开发期发现并修复的两个缺陷（已补回归断言，如实记录在 `verify/verification_record.md`）：

1. **改派未释放原执行人容量** → 容量单调泄漏，第 4 次改派会因「没人有空位」误升级到人工。
2. **轨迹时间戳与 seq 不同序** → 内层改派记录多取了一次时钟。

## 已知局限

候选打分为线性加权（偏好 5 分/位、技能 10 分/项、容量 5 分/格），权重是启发式而非学习得到；
不含时区/排班/技能等级等更细的可用性模型；规则表规模到数百条时应改为索引匹配。
