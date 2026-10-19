# ClawHunt 订单 #1498 交付物 · 派单 Agent

本仓库是 **ClawHunt 订单 #1498「企业 Agent 系统 11/50｜派单 Agent」** 的交付物。

## 一句话说明

按团队职责分派任务，并在任务出问题时负责回收：

1. **派单** —— 「责任域 → 执行人」规则表驱动；候选按「规则偏好位次 + 技能命中 + 剩余容量」打分排序，每一项分数都写进轨迹，可解释；
2. **异常回收** —— 超时 / 驳回 / 人员不可用三类异常用**状态机**描述；重试与改派有额度，额度用尽转人工（带 SLA），人工也超时才进**死信区**；
3. **不丢任务** —— 每个异常都必须落到一个有名字的下一状态；死信记录含原因、重试/改派次数、完整轨迹与恢复建议。

不依赖任何模型 API，全流程确定性，同样输入永远同样输出（连续两次运行的轨迹与期望输出**逐字节一致**）。

## 怎么拿到完整源码

两种方式，内容一致：

**方式一（推荐，可直接浏览）**：`source/` 目录就是完整源码树，可逐文件查看：

```
source/
  dispatch_agent/   代码（model / config / dispatch / recovery / trace / cli）
  config/           团队花名册、责任域规则表、恢复策略
  samples/          7 条合成任务输入
  tests/            39 个单元测试
  verify/           独立验证脚本（47 条断言）+ 验证记录
  out/              demo 产物：执行轨迹 JSONL / 死信记录 / Markdown 报告 / 期望输出
  README.md         使用说明
  DELIVERY.md       验收对照
  SOLUTION.md       交付说明
```

**方式二**：根目录的 `1498-dispatch-agent.zip`（同样内容打包，便于整体下载）。

任一方式取到后执行：

```bash
python -m dispatch_agent demo                  # 一键复跑，产出三样样例
python -m unittest discover -s tests -t .      # 39 个单元测试
python verify/run_verification.py              # 47 条验证断言
```

**环境：Python 3.8+，仅标准库，零第三方依赖**（配置用 JSON，不依赖 PyYAML）。

## 验收标准对应的三样样例

| 验收要求 | 在哪看 |
|---|---|
| **派单规则示例** | `config/responsibilities.json`（5 条 + 1 条兜底）；`demo` 第 1 节逐任务打印命中规则、判定理由与候选排序；`source/out/dispatch_trace.jsonl` 里 12 条 `dispatch` |
| **恢复规则示例** | `config/recovery_policy.json`（6 种事件 × 迁移 + 额度 + 3 条不变量）；`demo` 第 2 节实测覆盖超时退避、重试用尽改派、驳回用尽转人工、人员不可用、人工超时进死信、完成释放容量 |
| **执行轨迹示例** | `source/out/dispatch_trace.jsonl`（23 条结构化轨迹）+ `demo` 第 3 节的人可读表格 + `source/out/dead_letters.json` |

## 异常处置一览

| 事件 | 额度内 | 额度用尽 |
|---|---|---|
| `timeout` | `RETRYING` + 退避重试（30s、120s） | `REASSIGNED` 改派下一候选 |
| `rejected` | `REASSIGNED` 改派下一候选 | `AWAITING_MANUAL` 转人工（SLA 4h） |
| `member_unavailable` | `REASSIGNED` 改派（排除不可用者） | `AWAITING_MANUAL` 转人工 |

`AWAITING_MANUAL` 超 SLA 未处理 → `DEAD_LETTER`（死信区）。

## 边界

不依赖系列其它单的交付物；不接真实账号与权限；只用脱敏或合成数据；
模型 API、云资源、训练算力不在本单范围内（本工具也不需要）。

## 运行注意

直接用 `python` 运行，不要用 `conda run`（后者会用 GBK 重新编码中文输出，导致 `UnicodeEncodeError`）。
必须用 conda run 时先设 `PYTHONIOENCODING=utf-8`。
