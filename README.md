# 短视频脚本 Agent（题目 4）

交付版本：题目 4，短视频脚本 Agent。A01—A07 与检索结果对照 C01 共 8 项保存样本验收通过，81 项离线回归通过，归档 9 条完整真实运行记录，并已在不含密钥的新虚拟环境中复核。

公开仓库：[z15254775933/shortvideo-script-agent](https://github.com/z15254775933/shortvideo-script-agent)，主分支 `main`。最终 SHA 用 `git rev-parse HEAD` 获取，交付检查见 [最终复核](docs/07-final-verification.md)。

建议先看 [交付与评审导航](docs/06-submission-guide.md)，AI 辅助及个人参与记录见 [AI 使用说明](docs/04-ai-usage.md)。

## 离线评审入口

在仓库根目录执行，无需密钥或网络：

```powershell
python -m src.shortvideo_agent evaluate
python -W error::ResourceWarning -m unittest discover -s tests -v
```

`evaluate` 读取 `data/evaluation_cases.json`，重算成功脚本的时长与规则检查，核对 Trace、引用、版本和调用上限，再检查各场景的真实观察与后续模型动作。已保存报告为 `examples/phase05/acceptance.actual.json`，人类可读说明为 `docs/03-evaluation.md`。这里的样本通过数不是模型总体成功率。

## 环境与运行

Python 3.11 或以上，无第三方运行时依赖。当前实际验证环境为 Windows PowerShell、Python 3.14.4；尚未在其他 Python 版本和操作系统实测。以下命令均在仓库根目录运行，无需安装包或激活虚拟环境。

```powershell
python --version
python -m src.shortvideo_agent --help
python -m src.shortvideo_agent inspect --input examples/inputs/normal.json
python -m src.shortvideo_agent inspect --input examples/inputs/missing_duration.json
python -m src.shortvideo_agent check-model --mode mock
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json
python -m unittest discover -s tests -v
```

`inspect` 只校验输入并读取素材，不调用模型。正常输入返回 `inspection_status: ready`；缺少目标时长的例子返回 `needs_input` 和缺失项。它们是输入检查结果，不是业务脚本生成结果。

`check-model --mode mock` 无需密钥与网络，固定返回 `OK`，输出明确标记 `mode: mock`、`scripted: true`、`evidence_scope: flow_only`。该模式仅验证离线诊断流程，不证明真实模型决策有效。

## 真实模型配置

首次使用且没有 `.env` 时，复制占位模板：

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

在本地 `.env` 填写自己的 `DEEPSEEK_API_KEY`，不要提交真实值。支持的配置：

| 变量 | 默认值或用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 仅真实调用需要；不设默认密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-flash` |
| `MODEL_TIMEOUT_SECONDS` | `30`，单次请求超时秒数 |
| `AGENT_MAX_STEPS` | `10`，Agent 的模型决策步数上限 |
| `AGENT_MAX_TOOL_CALLS` | `16`，全部工具调用上限，包含终止动作 `finish_task` 和无效调用 |
| `AGENT_MAX_OUTPUT_TOKENS` | `4096`，每次模型响应的最大输出 token 数 |

同名进程环境变量优先于 `.env`。配置文件支持简单 `KEY=VALUE`、注释和外围引号，不支持变量展开或多行值。当前适配器只向 DeepSeek 官方 HTTPS 主机发送凭据，并禁止请求自动重定向。

真实连接诊断会发起一次最多输出 16 tokens 的请求：

```powershell
python -m src.shortvideo_agent check-model --mode real
```

该连接诊断仅验证认证及基础文本调用；真实 Agent 的完整运行见下一节。真实模式失败会明确返回错误，不自动转为 Mock，也不自动重试模型请求。

## 运行 Agent

离线执行预设流程，或者显式选择真实 DeepSeek：

```powershell
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json
```

默认是 Mock；Mock 动作和脚本全部预设，只验证执行流程，不能证明模型动态决策。它使用示例资料，不能替代对任意输入的真实生成。真实模式会进行多轮 API 请求，受配置的轮数与工具调用上限控制。

模型自主选择检索、提交或修改脚本、估时、规则检查和结束。脚本通过 `estimate_duration` 或 `check_rules` 的参数提交，程序分配修订号；修改正文、引用、停顿或画面预算后旧检查失效。只有当前版本的两项实际检查通过、来源已经检索且关键输入齐全，模型提交的成功状态才会被接受。

每次运行默认创建 `examples/runs/<唯一目录>/`，也可用 `--output-dir 新目录` 指定。已有目录不会覆盖。产物包含：

- `result.json`：任务状态、可编辑脚本、实际检查、引用、风险与补充问题。
- `script.md`：便于阅读和修改的脚本文本，标明运行模式与未完成状态。
- `trace.json`：完整输入、模式、配置、动作参数、观察结果、稿件版本及终止原因。
- `events.jsonl`：执行期间逐事件写入的记录。强制杀死进程时可能只有此文件；正常结束和可处理的中断才生成完整产物。

可检查并修改已有草稿、验证空素材或设置更低的上限：

```powershell
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --initial-script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --materials examples/agent_inputs/empty_materials.json
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json --max-steps 1
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json --max-tool-calls 1
```

`--initial-script` 的来源会标记为提供的输入，不能把初稿称作模型生成。还可用 `--fail-once search_materials` 等显式注入一次业务工具故障；故障带标记，是否恢复由后续模型决定。模型请求自身的网络错误会如实返回未完成，不转成虚构结果。

## 数据格式与保存结果

输入样例位于 `examples/inputs/`。合成产品素材与品牌规则位于 `data/`，均明确标注 `synthetic: true`。

```powershell
python -m src.shortvideo_agent schema brief
python -m src.shortvideo_agent schema script
python -m src.shortvideo_agent schema trace
```

支持导出 `brief`、`materials`、`rules`、`script`、`result`、`trace` 六种版本 1 数据契约。校验器只实现项目所使用的 JSON Schema 关键字，不声称兼容整个 JSON Schema 标准。结构合法不等于事实正确或业务成功。

输入检查、连接诊断和 Schema 导出均支持 `--output` 保存 JSON，例如：

```powershell
python -m src.shortvideo_agent inspect --input examples/inputs/normal.json --output examples/local/normal-inspection.json
```

输出文件若已存在，命令直接报错，不覆盖旧结果。再次运行请使用新的文件名。真实密钥和常见授权字段在诊断输出中会脱敏。

退出码：`0` 为工具执行正常且检查通过（检索无结果仍为正常执行）；`2` 为需要补充信息、输入校验失败或业务检查不通过；`3` 为模型、配置、连接诊断或工具执行失败；`4` 为文件操作失败。解析命令行参数失败同样使用 `2`。在 PowerShell 脚本中可用 `$LASTEXITCODE` 读取 Python 进程的退出码。

## 单独运行三个业务工具

这些命令完全离线，不需要密钥或模型调用。输入脚本是开发阶段预先构造、由 AI 助手编写的测试夹具，不是业务 Agent 在线自主生成的脚本，也不代表提交者手写过这些初稿。

```powershell
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 字幕
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 降噪
python -m src.shortvideo_agent tool estimate --input examples/inputs/normal.json --script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent tool estimate --input examples/inputs/normal.json --script examples/tool_inputs/within_budget.json
python -m src.shortvideo_agent tool check --input examples/inputs/normal.json --script examples/tool_inputs/within_budget.json
python -m src.shortvideo_agent tool check --input examples/inputs/normal.json --script examples/tool_inputs/unsupported_claim.json
```

时长工具重新计算分镜时长，忽略输入脚本自报的估时。目标时长取自需求文件，模型不能通过工具参数修改目标或语速。

规则工具采用保守的“素材原句＋有限连接短语”政策：要求引用真实存在且属于当前产品的事实，保留全部限定，并检查标题、画面描述、旁白、字幕有没有额外表述。未经支持的文字会被阻断；安全的自由改写也可能被阻断。这是受限文案政策，不是任意自然语言语义核验。允许的短语随检索与检查结果返回。

每次时长和规则检查都返回脚本修订号及 SHA-256 指纹，供第四步绑定检查结果。`status: ok` 表示工具执行正常，业务条件是否满足看内部的 `passed`；不应把“检查发现超时”误报成工具故障。

可显式注入一次有标记的工具故障：

```powershell
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 字幕 --simulate-failure
```

该命令返回 `simulated_failure: true`，不自动重试，不证明模型会恢复故障。所有工具子命令也支持 `--output` 保存结果。

## 评审入口

- `docs/01-requirements.md`：需求与验收清单，包含 A01—A07 保存样本的通过状态。
- `docs/02-solution.md`：当前架构、字段约定、技术取舍和后续职责。
- `docs/phase02-validation.md`：第二步实际验证结果及证据范围。
- `docs/03-evaluation.md`：当前完整验收矩阵、实际结果、对照方法和限制。
- `docs/04-ai-usage.md`：开发辅助、运行时模型、Mock 与当前个人参与记录。
- `docs/05-retrospective.md`：实际工程难点、迭代、学习点、阶段计时和后续改进。
- `docs/06-submission-guide.md`：阅读顺序、评审命令和第七步提交信息。
- `docs/07-final-verification.md`：不含密钥的独立目录与新虚拟环境复核、公开交付入口。
- `docs/phase04-validation.md`：三条真实 Agent 路径、执行上限与第四步验证记录。
- `examples/phase02/`：CLI 保存的真实诊断输出，含单独标识的离线 Mock 输出。
- `examples/phase03/`：八份业务工具实际输出，不能替代模型决策 Trace。
- `examples/phase04/`：三条真实模型路径与三条明确标记的 Mock 路径，包含完整结果、脚本和 Trace。
- `examples/phase05/`：缺失信息、工具故障、无依据数字修正和真实执行上限的完整记录，以及明确标记为单步的检索对照。
- `examples/README.md`：输入、预设夹具、完整运行及单步对照的统一索引。
- `tests/test_foundation.py`：离线基础测试，不调用真实模型或读取真实密钥。
- `tests/test_tools.py`：检索、时长、事实与品牌约束、错误边界等离线测试。
- `tests/test_agent.py`：用固定模型响应验证执行边界与版本校验；这些测试不证明模型决策效果。
- `tests/test_evaluation.py`：离线验收、篡改证据拒绝、跨机器路径和共享前缀对照审计。

可重新执行一次真实的单步对照：

```powershell
python -m src.shortvideo_agent compare-retrieval --source-run examples/phase04/real-normal
```

该命令复用保存的真实首轮工具选择，在相同前缀下改变检索返回，然后各发起一次新模型请求；下一步动作只记录、不执行，不能把对照当成两次完整任务。

提交者个人复核记录只能在实际操作后追加；当前 AI 辅助范围与限制已如实说明。评审入口、公开仓库和最终 SHA 查询方式均已给出。
