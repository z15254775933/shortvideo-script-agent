# 短视频脚本 Agent｜题目 4

根据产品资料生成有来源、满足时长上限、可继续编辑的短视频脚本。资料不足时请求补充；超时或违规时由模型观察工具反馈、修改并重新检查。

公开仓库：[z15254775933/shortvideo-script-agent](https://github.com/z15254775933/shortvideo-script-agent)，分支 `main`。提交 SHA：`git rev-parse HEAD`。

当前版本 **0.2.0**。11 项保存样本验收；新增创作模式、独立文案审核、分镜时间轴和审核调用统计。AI 辅助范围与提交者参与见 [AI 使用说明](docs/04-ai-usage.md)。

## 先看实际结果

- [抖音情境脚本](examples/phase06/creative-douyin-final/script.md)：具体开场、拍摄建议、逐镜时间和素材引用。
- [B站解释型脚本](examples/phase06/creative-bilibili/script.md)：相同两条产品事实，说明已知能力与资料边界。
- [无依据自动化宣传修正](examples/phase06/creative-semantic-repair-valid/script.md)：先审核提供的错误初稿，观察驳回，再修改、复查。
- [超时改稿](examples/phase04/real-overlong-repair/script.md)：实际 43.5 秒改为 24 秒，保留修改前后检查。

建议评审先看上述脚本，再对照同目录的 `result.json`、`trace.json`、`events.jsonl`。完整证据与已发现的审核漏检见 [本轮优化与验证](docs/08-improvements.md)，项目理解见 [阅读与复核导读](docs/09-walkthrough.md)。

## 无密钥复现

要求 Python 3.11+，无第三方运行时依赖，无需安装包。实际测试环境为 Windows、Python 3.14.4；以下命令在仓库根目录运行。

```powershell
git clone https://github.com/z15254775933/shortvideo-script-agent.git
cd shortvideo-script-agent
python -m src.shortvideo_agent evaluate
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json
```

`evaluate` 对当前 11 项保存样本离线审计，新增模型调用为 0。严格模式重算所有检查；创作模式重算确定性检查并校验已保存审核的输入指纹、字段覆盖、原始响应和调用记录，不重新裁决自然语言真值。通过数不代表模型总体成功率。

Mock 动作和脚本全部预设，仅验证流程；输出明确标记 `mode: mock`，不证明真实模型决策效果。

## 真实生成

首次使用且没有 `.env` 时复制模板，在本地填写自己的 `DEEPSEEK_API_KEY`：

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/bilibili.json
```

`run` 默认是 Mock；显式选择 `--mode real` 后默认采用 `creative` 创作模式，发生真实 API 调用。旧版严格文案模式可用 `--writing-mode strict`。真实运行失败会如实返回错误或未完成，不自动转为 Mock。

| 写作模式 | 表达与事实约束 | 模型调用 |
| --- | --- | --- |
| `strict` | 素材原句及有限连接短语；可能误拦安全文案 | Agent 决策 |
| `creative` | 事实原句、限定和引用仍须保留；标题、转场和拍摄建议可自由表达，接受独立审核 | Agent 决策＋模型审核工具 |

创作模式仍是单 Agent。审核工具用独立对话检查标题、画面、旁白和字幕，没有选工具或结束任务的权限。它与生成器使用同一模型服务，可能相关误判。已观察到的“无需重剪／重录”等工作流承诺另有确定性检查；该检查只覆盖列出的短语，不宣称通用语义正确性。

## 输入、工具与输出

输入包含主题、受众、平台、目标时长、风格及可选 `product_id`；产品素材和品牌规则为本地 JSON。示例资料均标注为合成，不代表真实产品能力。

```powershell
python -m src.shortvideo_agent inspect --input examples/inputs/normal.json
python -m src.shortvideo_agent schema brief
python -m src.shortvideo_agent schema script
python -m src.shortvideo_agent tool search --input examples/inputs/normal.json --query 字幕
python -m src.shortvideo_agent tool estimate --input examples/inputs/normal.json --script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent tool check --input examples/inputs/normal.json --script examples/tool_inputs/within_budget.json
```

以上工具命令默认完全离线。显式为 `tool check` 加 `--writing-mode creative` 才会发起最多一次独立审核请求，需要本地模型配置。

每次完整运行创建一个新目录，默认 `examples/runs/<唯一ID>/`，也可指定 `--output-dir 新目录`，已有目录不会覆盖：

| 文件 | 内容 |
| --- | --- |
| `script.md` | 可编辑脚本；创作模式附逐镜时间轴、旁白、字幕、画面、来源和实际检查 |
| `result.json` | 状态、需求、脚本、检查、风险及补充问题 |
| `trace.json` | 模型动作、完整参数与观察、稿件版本、终止原因；创作模式另存审核原始响应和调用计数 |
| `events.jsonl` | 逐事件日志，可与最终 Trace 核对；强制结束进程时可能只有部分日志 |

模型自行选择检索、提交／修改脚本、估时、规则检查和结束。程序分配修订号，实质改稿后清除旧检查。成功必须有当前同版的两项通过检查、已检索的引用以及完整输入；模型自报时长不作为结果。

时长按固定语速、字幕阅读、画面预算与停顿估算：每镜取较长占用，向上取整到 0.1 秒再求和。它是估算，不等于实际成片计时。

## 执行边界与调用成本

| 配置 | 默认 |
| --- | --- |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | `https://api.deepseek.com` / `deepseek-flash` |
| `MODEL_TIMEOUT_SECONDS` | 每次请求 30 秒 |
| `AGENT_MAX_STEPS` | 10 次 Agent 决策请求 |
| `AGENT_MAX_TOOL_CALLS` | 16 次工具调用，包含终止和无效调用 |
| `AGENT_MAX_OUTPUT_TOKENS` | 每次 Agent 响应最多 4096 tokens |
| `--max-review-calls` | 创作模式额外最多 4 次审核请求，每次最多 4096 输出 tokens |

默认完整创作任务最多发起 14 次模型请求。审核请求单独计数，失败也消耗预算，相同审核输入可复用缓存；不会自动重试。审核失败、漏审、非法引用、响应格式错误或达到审核上限均不能视为通过。总调用量及已返回 token 用量见 Trace 和验收报告；未返回用量的失败请求不能当作零成本。

完整审核输入和响应保留在 Trace；Agent 只接收检查结论、具体问题及摘要，减少重复上下文。单个样本的调用量不能证明总体成本下降。

```powershell
python -m src.shortvideo_agent run --mode real --input examples/inputs/review_creative_unsupported.json --initial-script examples/tool_inputs/creative_unsupported.json
python -m src.shortvideo_agent run --mode real --writing-mode strict --input examples/inputs/normal.json --initial-script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --materials examples/agent_inputs/empty_materials.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --fail-once search_materials
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json --max-steps 1
```

初稿是提供的输入，会记录来源；`tool_inputs/` 中的夹具由开发 AI 预先编写，不能算作运行时 Agent 自主生成。故障注入有明确标记，恢复动作由模型选择。`incomplete` 为未完成，`needs_input` 为需要补充。

同名进程环境变量优先于 `.env`；适配器仅向 DeepSeek 官方 HTTPS 主机发送凭据并禁止自动重定向。真实密钥被 Git 忽略，输出会脱敏。标准库 Schema 校验器只支持本项目使用的关键字，不声称完整实现 JSON Schema。

退出码：`0` 为正常通过；`2` 为补充信息、输入无效或检查不通过；`3` 为执行／模型错误或未完成；`4` 为文件操作失败。检索空结果仍为正常工具执行。输出不覆盖已有文件。

## 文档与评审入口

- [需求与验收](docs/01-requirements.md)、[方案与技术取舍](docs/02-solution.md)
- [测试预期、实际结果和限制](docs/03-evaluation.md)、[样例索引](examples/README.md)
- [AI 使用与个人参与](docs/04-ai-usage.md)、[工程复盘](docs/05-retrospective.md)
- [提交信息](docs/06-submission-guide.md)、[首次交付复核](docs/07-final-verification.md)
- [本轮优化与验证](docs/08-improvements.md)、[阅读与复核导读](docs/09-walkthrough.md)

提交者本人复核和学习记录只能依据实际操作追加；当前文档如实区分开发 AI、运行时模型、Mock 与提交者参与。
