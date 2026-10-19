【交付物获取方式】
本单 delivery_channel=platform_only，平台无附件上传通道，评审只读提交正文。
因此本正文自包含：交付物结构、配置、机制、脱敏输入、完整执行轨迹样例、一键复跑命令、
预期输出与验证记录均写在正文里，无需下载即可核验。

完整交付物（27 个文件，公开可浏览）：
  仓库：https://github.com/Code-play/clawhunt-1498-dispatch-agent
  源码树：https://github.com/Code-play/clawhunt-1498-dispatch-agent/tree/main/source
  打包：https://github.com/Code-play/clawhunt-1498-dispatch-agent/raw/main/1498-dispatch-agent.zip

【订单与范围】
订单 #1498「企业 Agent 系统 11/50｜派单 Agent」。
本单范围：配置按团队职责分派任务与异常回收的 Bot。
验收标准：Provides examples of dispatch rules, recovery rules, and execution traces.
投标承诺：以「责任域 → 执行人」规则表驱动派单；异常用状态机描述（超时、驳回、人员不可用）
并给出恢复动作；附一次完整执行轨迹。以上三项均已交付并可复跑。

【买家助手两问的正面回答】
1) 前置依赖：**不依赖系列任何其它单**（#1494 等）。本单是自包含的独立可运行包：
   自带团队花名册、规则表、恢复策略与合成任务输入，无外部服务、无数据库、无模型 API。
2) 脱敏数据范围：**验证全部用合成/脱敏数据构造，不需要买家提供任何真实数据**。
   samples/tasks.jsonl 是 7 条合成的任务（域/类型/优先级/技能标签），config/team.json 是
   脱敏团队花名册（只有责任域、技能标签与容量，无姓名、账号、联系方式）。
   真实团队接入时只替换这两个 JSON 即可，代码不动。

【交付物清单】共 27 个文件
  dispatch_agent/model.py      领域模型（任务/执行人/候选/决策/异常记录）
  dispatch_agent/config.py     JSON 配置加载与校验（团队/规则表/恢复策略）
  dispatch_agent/dispatch.py   规则匹配 + 候选打分排序（派单规则）
  dispatch_agent/recovery.py   异常状态机 + 死信区（恢复规则）
  dispatch_agent/trace.py      执行轨迹记录与渲染（执行轨迹）
  dispatch_agent/cli.py        命令行入口：demo / dispatch
  config/team.json             团队花名册（脱敏）
  config/responsibilities.json 「责任域 → 执行人」规则表（5 条 + 1 条兜底）
  config/recovery_policy.json  恢复策略：状态、迁移、额度、不变量
  samples/tasks.jsonl          7 条合成任务输入
  tests/                       39 个单元测试（标准库 unittest）
  verify/run_verification.py   独立验证脚本（47 条断言）
  verify/verification_record.md / verification_result.json
  out/dispatch_trace.jsonl     执行轨迹（23 条，确定性可重建）
  out/dead_letters.json        死信记录
  out/dispatch_report.md       Markdown 报告
  out/expected_output.txt      期望输出（用于比对复跑）
  README.md / DELIVERY.md / SOLUTION.md / .gitignore

【环境要求与一键复跑】
环境：Python 3.8+（实测于 3.13）；**仅标准库，零第三方依赖**（配置用 JSON，不依赖 PyYAML）；
不联网、不调用任何模型 API、不需要数据库。
命令：
  cd 1498-dispatch-agent
  python -m dispatch_agent demo                    # 产出三样样例 + 轨迹 + 报告
  python -m unittest discover -s tests -t .        # 39 个单元测试
  python verify/run_verification.py                # 47 条验证断言
  python -m dispatch_agent dispatch --task-json '{"id":"T-X","title":"临时任务","domain":"backend","task_type":"api","priority":4,"required_skills":["api"]}'
预期输出（demo 摘要，确定性，两次运行逐字节一致）：
  团队规模: 6 人；规则 5 条 + 兜底 1 条；状态机事件 6 种
  [T-1001] 命中规则 R-010 → 选中 M-BE-01（偏好第 1 位+40；技能命中 api,db +20；容量 2 +10）
  [T-1006] 无规则命中 → 兜底 R-999 → 无可用候选 → 升级人工（任务不丢）
  [T-1001] timeout: ASSIGNED → RETRYING / retry_with_backoff（退避 30s → 120s）
  [T-1001] timeout: RETRYING → REASSIGNED / reassign_next_candidate
  [T-1001] rejected: REASSIGNED → AWAITING_MANUAL / escalate_to_human（SLA 4h）
  [T-1001] manual_timeout: AWAITING_MANUAL → DEAD_LETTER / park_in_dead_letter
  轨迹条目统计: {"dispatch": 12, "escalation": 1, "recovery": 10, "total": 23}
产物：out/dispatch_trace.jsonl（执行轨迹）、out/dead_letters.json（死信）、
      out/dispatch_report.md（报告）、out/expected_output.txt（用于比对复跑）

【派单规则机制】
规则表 config/responsibilities.json 的每条规则 = 匹配条件 + 分派目标 + 无候选时动作：
  匹配条件：domain（责任域，* 表示不限）、task_type_in（类型白名单）、
            priority_at_least（优先级下限）、tags_any（标签命中任一）
  分派目标：domain_owner（责任域）+ preferred（执行人偏好顺序）
  无候选时：escalate_manual（转人工分派，绝不静默丢弃）
匹配顺序：按 priority 从大到小取第一条命中；全部不命中走 default_rule（兜底转人工）。
候选打分（可解释，逐项写入轨迹）：
  + 规则偏好第 n 位：40 - 5×(n-1) 分
  + 技能命中：每项 10 分（required_skills ∩ member.skills）
  + 剩余容量：每格 5 分（capacity - load）
  排除条件：责任域不符 / 不可用 / 容量已满 / 被显式 exclude
实测 5 条规则：R-010 后端接口→backend；R-011 后端队列→backend（队列优先）；
R-020 数据加工→data；R-030 高优运维→ops（无人则转人工）；R-040 带 cross-team 标签→qa 复核。

【恢复规则机制：异常状态机 + 死信区】
状态：ASSIGNED 已派单 / RETRYING 退避重试中 / REASSIGNED 已改派 /
      AWAITING_MANUAL 转人工（带 SLA）/ DEAD_LETTER 死信区 / DONE 完成
事件与迁移（config/recovery_policy.json，代码不硬编码策略）：
  timeout            额度内 → RETRYING + retry_with_backoff（退避 30s、120s）
                     额度用尽 → REASSIGNED + reassign_next_candidate
  rejected           额度内 → REASSIGNED + reassign_next_candidate
                     额度用尽 → AWAITING_MANUAL + escalate_to_human
  member_unavailable 有替代 → REASSIGNED + reassign_excluding_unavailable
                     无替代 → AWAITING_MANUAL + escalate_to_human
  retry_exhausted    → AWAITING_MANUAL + escalate_to_human（SLA 4h）
  manual_timeout     → DEAD_LETTER + park_in_dead_letter（next_state=AWAITING_MANUAL）
  completed          → DONE + release_capacity
额度：max_retries=2、max_reassigns=2、backoff=[30,120]s、manual_sla_hours=4。
三条不变量（代码强制，违反即抛 RecoveryError，不静默吞掉）：
  1) 每个异常事件都必须能匹配到一条 from 命中的迁移；
  2) 进死信区的记录必须含任务、原因、重试/改派次数、完整轨迹、恢复建议、下一状态；
  3) AWAITING_MANUAL 必须带 SLA，超时后自动进死信区而不是消失。
死信记录实测（可检查、可接手）：
  {"task_id":"T-1001","reason":"人工接管超时未处理（触发事件 manual_timeout）",
   "retry_count":2,"reassign_count":3,"last_assignee":null,
   "recovery_suggestion":"核对责任域规则表是否缺少可承接该域的成员；补人后从 AWAITING_MANUAL 重新派发。",
   "next_state":"AWAITING_MANUAL","inspectable":true,"trace":[…23 步中的 8 步…]}

【执行轨迹样例（完整 23 条见 out/dispatch_trace.jsonl，节选）】
每条轨迹 = seq + step + 时间 + 任务 + 规则/迁移 + 可读理由；时间为确定性时钟（固定起点 + 90s 步长）。
  {"seq":1,"step":"dispatch","at":"2026-01-05T09:00:00Z","origin":"initial","task_id":"T-1001",
   "rule_id":"R-010","chosen":"M-BE-01","escalated":false,
   "candidates":[{"member":"M-BE-01","score":70.0,"reason":"规则偏好第 1 位(+40)；技能命中 ['api','db'](+20)；剩余容量 2(+10)"},
                 {"member":"M-BE-02","score":55.0,"reason":"规则偏好第 2 位(+35)；技能命中 ['api'](+10)；剩余容量 2(+10)"}],
   "reason":"命中 R-010（责任域=backend，任务类型 api ∈ ['api','service']）→ 选中 M-BE-01（…）"}
  {"seq":9, "step":"recovery","at":"2026-01-05T09:12:00Z","task_id":"T-1001","kind":"timeout",
   "from_state":"ASSIGNED","to_state":"RETRYING","action":"retry_with_backoff",
   "detail":"执行人未在 SLA 内受理","extra":{"retry_count":1,"backoff_seconds":30},"assignee":"M-BE-01"}
  {"seq":18,"step":"recovery","at":"2026-01-05T09:25:30Z","task_id":"T-1001","kind":"manual_timeout",
   "from_state":"AWAITING_MANUAL","to_state":"DEAD_LETTER","action":"park_in_dead_letter",
   "extra":{"inspectable":true,"next_state":"AWAITING_MANUAL"}}
终态汇总（7 条任务无一丢失）：T-1001 DEAD_LETTER；T-1002 ASSIGNED；T-1003 DONE；
  T-1004 AWAITING_MANUAL；T-1005 ASSIGNED；T-1006 AWAITING_MANUAL；T-1007 ASSIGNED。

【验收标准逐条对照】
1) 派单规则示例（dispatch rules）：规则表 5+1 条；7 条任务逐条给出命中规则、判定理由与
   候选排序（含分数构成），见 demo 第 1 节与 out/dispatch_trace.jsonl 的 12 条 dispatch。
2) 恢复规则示例（recovery rules）：6 种事件 × 迁移表；实测覆盖超时退避、重试用尽改派、
   驳回用尽转人工、人员不可用（有替代/无替代）、人工超时进死信、完成释放容量，
   见 demo 第 2 节与 10 条 recovery 轨迹。
3) 执行轨迹示例（execution traces）：23 条结构化轨迹（JSONL）+ 人可读表格 + 死信记录，
   每步带规则/迁移与理由，可逐步核对。

【验证记录】
`python verify/run_verification.py`：**47/47 断言通过**（退出码 0），刷新
verify/verification_record.md 与 verification_result.json。
`python -m unittest discover -s tests -t .`：**39/39 通过**。
关键断言：配置加载与非法配置拒绝；7 条任务均有规则与理由；无候选升级而非丢弃；
候选排序（技能命中压过偏好位次、容量约束）；超时退避 30/120s；重试/改派额度与转人工 SLA；
人员不可用两条路径；死信记录字段齐全；未定义事件抛 RecoveryError；完成释放容量；
轨迹 JSONL 可解析、seq 连续、**时间戳单调不减**；demo 复跑两次产物逐字节一致。
其中两条是开发期发现缺陷后补的回归断言，如实说明：
  a) 改派未释放原执行人容量 → 容量单调泄漏，第 4 次改派会因"没人有空位"而误升级到人工。
     已在 recovery.py 修复（改派/转人工时释放容量），并加断言「改派释放原执行人容量」。
  b) 内层改派记录多取了一次时钟，导致轨迹时间戳与 seq 不同序。已改为共用同一时间戳，
     并加断言「demo 轨迹时间戳单调不减」。

【关键设计取舍 / 已知局限】
- 不用大模型：本单预算不含模型 API 费用；且验证记录要能被买家复跑比对，接模型后输出不确定。
  规则表 + 打分排序是可解释的确定性逻辑，出问题能定位到具体规则与分数项。
- 配置与代码分离：换团队/换规则/换额度只改 3 个 JSON，不动代码。
- 已知局限（如实说明）：候选打分为线性加权（偏好 5 分/位、技能 10 分/项、容量 5 分/格），
  权重是启发式而非学习得到；不含时区/排班/技能等级等更细的可用性模型；
  规则表规模到数百条时应改为索引匹配。以上均可在后续单里按需扩展。

【范围与排除】
- 不依赖系列其它单的任何交付物，独立可运行。
- 不接真实账号/权限，不采集任何真实个人数据；只用脱敏或合成数据。
- 模型 API、云资源、训练算力等第三方费用不在本单范围内（本工具也不需要）。
- 真实团队接入、排班与容量策略校准属超范围项，可在客户经平台提供脱敏数据后另行对接。

【运行注意】
直接用 python 运行，不要用 conda run：conda 会用自己的 GBK 编码重新打印子进程输出，
含中文时表现为 UnicodeEncodeError 且退出码 1（是 conda 的输出重编码问题，不是本工具的问题）。
若必须用 conda run，请先设 PYTHONIOENCODING=utf-8。
