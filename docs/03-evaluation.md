# 评估与验收

状态：第五步完成。A01—A07 与检索结果对照 C01 共 8 项保存样本验收通过；81 项离线回归全部通过。这里的通过是已保存样本的结果，不是模型统计成功率。

机器报告：`examples/phase05/acceptance.actual.json`；验收映射：`data/evaluation_cases.json`。可不配置密钥直接执行 `python -m src.shortvideo_agent evaluate` 重新核对证据。另保留初次审计的 `evaluation.actual.json`，最终评审以 `acceptance.actual.json` 为准。

## 1. 验证方式与输入来源

Windows PowerShell、Python 3.14.4，运行时仅使用标准库。最终离线回归 81 项全部通过：基础 16 项、工具 31 项、Agent 边界 22 项、保存证据审计 3 项、验收及对照审计 9 项。测试使用预设响应或已保存输出，不调用模型或读取真实密钥。

真实效果来自 9 次完整 DeepSeek 运行与 2 次新增的对照后续决策。另有 3 条明确标记的完整 Mock 流程，不计为真实模型效果。所有完整运行的结果、可编辑脚本、Trace 和事件日志均保存于 `examples/phase04/`、`examples/phase05/`。

`examples/tool_inputs/` 下的脚本是开发阶段由 AI 助手预先构造的夹具，`data/` 是明确标注的合成产品资料与品牌规则。它们不代表提交者手工撰写，也不是业务 Agent 在线自主生成的结果，不能作为模型动态决策证据。详细区分见 `docs/04-ai-usage.md`。

## 2. 端到端验收矩阵

每个完整运行目录均包含 `result.json`、`script.md`、`trace.json`、`events.jsonl`。机器审计检查来源、脚本指纹、日志、调用数、当前版本检查，并对成功稿件重新估时和执行规则核验。

| 项目 | 预期 | 实际结果 | 主证据目录 |
| --- | --- | --- | --- |
| A01 正常生成 | 输出完整、有依据且满足目标 | 四镜脚本 28.2 秒，同版本检查通过 | `examples/phase04/real-normal/` |
| A02 缺失信息 | 提问补充，不自定时长 | 2 轮后请求目标时长，无脚本，`needs_input` | `examples/phase05/real-missing-duration/` |
| A03 无素材 | 改查或补充，不编造 | 4 次空检索后请求素材，无脚本 | `examples/phase04/real-no-materials/` |
| A04 工具故障 | 根据错误选后续动作，如实结束 | 观察显式检索故障后模型自主重试；最终 19.3 秒，检查通过 | `examples/phase05/real-search-failure/` |
| A05 超时修正 | 改稿后重新检查或明确失败 | 实际估时 43.5 秒后重写为 24.0 秒，两项检查通过 | `examples/phase04/real-overlong-repair/` |
| A06 无依据事实 | 指出效果数字问题，再改稿复查 | 仅 P01“支持字幕”资料；工具指出“效率提升80%”问题，模型删除并改稿为 21.9 秒，通过复查 | `examples/phase05/real-unsupported-reviewed/` |
| A07 执行边界 | 超限明确返回未完成 | 模型上限 1 次、工具上限 1 次的两个真实运行均正确停止 | `examples/phase05/real-step-limit/`、`real-tool-limit/` |
| C01 工具观察对照 | 其他上下文相同，观察变化后动作相应改变 | 有素材选择 `estimate_duration`；无素材选择两次新检索 | `examples/phase05/retrieval-comparison/` |

A07 的 `incomplete` 是该场景的正确预期，不是伪装成完成。A04 的工具故障由测试显式注入，后续模型调用均真实；它不代表测试了服务商真实网络事故。

## 3. 工具层实际结果

以下八份输出均由项目 CLI 实际执行并保存，未手工修改检查结果。文件均位于 `examples/phase03/`。

| 输入与工具 | 预期 | 实际结果 | 输出文件 |
| --- | --- | --- | --- |
| 30 秒需求，检索“字幕” | 命中已有素材，返回事实和来源 | 返回 P01、P02，共 2 条 | `search-hit.actual.json` |
| 同一需求，检索“降噪” | 明确无匹配资料 | 返回空列表，匹配数 0 | `search-empty.actual.json` |
| 估算 `overlong.json` | 忽略自报的 1 秒，识别超时 | 估时 43.5 秒，超出 13.5 秒，`passed: false` | `overlong-duration.actual.json` |
| 30 秒需求，估算 `within_budget.json` | 重新估时并通过 | 估时 13.7 秒，`passed: true` | `within-budget-duration.actual.json` |
| 改为 10 秒需求，估算同一短脚本 | 结果应随目标变化 | 仍估时 13.7 秒，超出 3.7 秒，`passed: false` | `ten-second-budget.actual.json` |
| 检查短脚本的引用及规则 | 两条产品事实可追溯 | 通过，列出 P01-F01 与 P02-F01 的逐镜引用 | `supported-script-check.actual.json` |
| 合法引用外额外添加“效率提升８０％” | 不能只因引用合法就放行 | 拦截旁白和字幕，返回 `unverified_text` 及 B01 对应的 `forbidden_phrase` | `unsupported-claim-check.actual.json` |
| 显式注入检索故障 | 返回错误，不伪造素材或自动重试 | `status: error`、`injected_failure`、`simulated_failure: true` | `injected-failure.actual.json` |

正常执行的工具，即使发现超时或违规，仍返回 `status: ok` 并以 `passed: false` 表示检查不通过；真正的工具故障返回 `status: error`。检索空结果是正常工具结果。

## 4. 可复现命令

在仓库根目录运行；所有命令均不调用模型：

```powershell
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m src.shortvideo_agent evaluate
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 字幕
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 降噪
python -m src.shortvideo_agent tool estimate --input examples/inputs/normal.json --script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent tool estimate --input examples/inputs/normal.json --script examples/tool_inputs/within_budget.json
python -m src.shortvideo_agent tool estimate --input examples/inputs/ten_seconds.json --script examples/tool_inputs/within_budget.json
python -m src.shortvideo_agent tool check --input examples/inputs/normal.json --script examples/tool_inputs/within_budget.json
python -m src.shortvideo_agent tool check --input examples/inputs/normal.json --script examples/tool_inputs/unsupported_claim.json
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 字幕 --simulate-failure
```

按预期不通过的检查返回退出码 `2`，模拟故障返回 `3`。添加 `--output 新文件路径` 可以保存自己的结果；已有文件不会覆盖。

重新运行真实业务场景及对照（需要本地密钥，每次创建新目录）：

```powershell
python -m src.shortvideo_agent run --mode real --input examples/inputs/missing_duration.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --fail-once search_materials
python -m src.shortvideo_agent run --mode real --input examples/inputs/review_unsupported.json --materials examples/agent_inputs/caption_only_materials.json --initial-script examples/tool_inputs/unsupported_claim.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --max-steps 1
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --max-tool-calls 1
python -m src.shortvideo_agent compare-retrieval --source-run examples/phase04/real-normal
```

## 5. 测试覆盖与限制

业务工具测试覆盖：命中与空结果、产品过滤、结果数量限制、来源不可变、中文／英文／数字估时、字幕与旁白同时呈现、停顿、向上取整、总时长求和、重算虚假估时、改变目标时长、合法引用、错误来源、扩大原意、遗漏限定、未引用事实、标题和画面中的额外断言、全角宣传数字、必须声明、空文本、重复分镜、脚本指纹、上下文绑定、错误参数、显式故障及异常脱敏。

已知限制和失败边界：

- 事实核验采用原句加有限连接短语政策。安全但不在政策中的改写也会被拒绝，例如额外加入“让我们开始吧”。这是明确的误拦边界，当前不宣称通用语义理解；风格和创意表达空间也受限。
- 数字的小数点、分数分隔符和百分号等保留在事实比较中，避免将“1.5 倍”误当“15 倍”。文字大小写、全半角和部分排版标点会规范化，不是对所有语言和符号的完整语义解析。
- 只能检查素材内部的一致性，不判断素材本身真假；不检查真实图片、声音或视频内容。
- 时长采用项目选定的假设语速和画面预算，不是实测成片时长。实际语速、数字读法、标点节奏和字幕阅读会造成误差。
- 检索是本地关键词匹配，不具备语义检索能力。命中“字幕”不会证明“自动识别”等查询附带描述。
- 版本绑定、旧检查失效、最终证据校验和执行次数上限已接入 Agent；边界由离线测试验证，真实模型在已保存路径中也遵守运行限制。
- A04 实际用了 9 轮，接近默认 10 轮上限，并经历了一次字段类型修正：首个估时请求的 `min_visual_seconds` 为 `null`，工具要求数字。模型随后改为数值并重试；这暴露了严格契约与文案政策带来的调用成本。不能用一条成功样本宣称稳定恢复或无限次可用。
- 没有用真人配音或真实视频验证估时，没有进行跨平台、跨模型或多次重复抽样，不能据此给出总体成功率。

## 6. 动态决策与受控对照的证据

A04：`real-search-failure/trace.json` 事件 5 返回显式故障。事件 9 是模型收到观察后的新响应，事件 10 自主选择“重试检索字幕功能资料”，没有程序自动重试。后续字段错误也由模型根据结构化反馈补齐，最终成功。

A05：见 `docs/phase04-validation.md`，包含真实超时观察、新稿及重新检查。

A06：`real-unsupported-reviewed/trace.json` 事件 6 报出 `unverified_text` 和 B01 `forbidden_phrase`。模型观察后在事件 11 提交重写稿，事件 12 注册修订 2，事件 13 估时 21.9 秒，事件 17 同版规则检查通过。初稿是事先提供的开发夹具，不是声称业务 Agent 先生成了假效果数字。

另保留 `real-unsupported-repair/`：普通生成请求下，模型在检查前主动删除了原稿中的效果数字并生成 21.9 秒脚本，因而没有“先检查报错”的链路。为单独验证这条链路，另一份输入 `review_unsupported.json` 明确要求先审稿，并将资料限制为仅 P01。两次原始结果均保留，主验收引用后者。

C01：从已保存真实正常运行的首轮检索选择重建共享前缀。两个分支的系统提示、需求、先前模型选择和工具参数相同，分别对实际有素材库和受控空库执行相同查询，然后各新增一次真实模型请求。

- 有素材：下一步选择提交草稿给 `estimate_duration`。
- 无素材：下一步选择 `search_materials("字幕")` 和 `search_materials("演示剪辑 功能说明")`。

`shared-prefix.json` 保存共享前缀及真实来源，两个 `*.next-decision.json` 保存实际观察和新响应，`summary.json` 记录对照结论。审计会核对共同指纹、原始模型选择、查询一致性，并重新执行两组检索来验证观察结果。

这是两个真实单步后续决策，未执行新动作，不能算两次完整 Agent 运行，也不代表统计因果结论。第三步的 13.7 秒脚本在 30 秒与 10 秒上限下不同检查结果仍仅作为工具层证据；本次模型动作对照采用检索结果这一变量。

## 7. 阶段记录与尚未交付内容

已记录的阶段区间（2026-10-28，Asia/Shanghai）：第二步 11:39:11—11:45:42，6 分 31 秒；第三步 12:13:48—12:24:15，10 分 27 秒；第四步 12:25:05—12:36:55，11 分 50 秒；第五步 12:38:23—12:51:56，13 分 33 秒，截至最终验证与敏感信息检查完成。

第五步最终检查 106 个可提交文件，真实密钥精确匹配为 0，`.env` 被 Git 忽略；输出未发现模型内部推理字段。未暂存、提交或推送。

第一步与前置讨论没有精确计时，阶段区间不包含讨论空档，不能当作从拿到题目开始的总用时。后续阶段记录见复盘；最终已在没有 `.env` 的独立目录、新建无第三方依赖虚拟环境中再次通过 8/8 审计与 81 项测试，见 `docs/07-final-verification.md`。公开仓库已创建，最终 SHA 以 Git 查询及交付回复为准。真实密钥保存在本地被忽略的 `.env`，提交前继续检查暂存内容。
