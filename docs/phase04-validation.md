# 第四步：真实模型驱动的工具循环

日期：2026-10-28，Asia/Shanghai。状态：Agent 核心循环及三条真实路径验证完成，完整验收矩阵留待第五步。

这是第四步完成时的阶段记录。第五步现已完成，当前完整验收以 `docs/03-evaluation.md` 和 `examples/phase05/acceptance.actual.json` 为准。

本记录中的“人工初稿”指开发阶段预先构造并从文件提供的测试夹具，具体内容由开发 AI 助手编写，不是提交者个人手写或业务 Agent 在线生成；见 `docs/04-ai-usage.md`。

## 1. 完成的能力

- DeepSeek 通过原生工具调用选择动作，接收真实结果，再选择后续工具、修改或结束。
- 程序执行工具、分配稿件修订号、维护实际来源与检查证据。没有程序预设的“超时即改稿”或“无素材即补充”决策分支。
- 原稿变化后全部旧检查失效；成功需要当前同一版脚本的估时和规则检查均通过，并且引用已通过实际检索取得。
- 最终状态通过独立的 `finish_task` 动作提交，不能与尚未观察结果的其他工具打包宣告成功。
- 默认最多 10 次模型请求、16 次工具调用（含终止与无效调用），超限明确返回未完成。
- 保存结果、可编辑 Markdown、完整 Trace 和逐事件日志；真实模式不回退 Mock。

## 2. 三条真实运行

模型：`deepseek-flash`；非思考模式。来源为合成产品资料，全部真实 API 调用均使用用户授权的本地凭据；未将密钥放入业务模型的输入消息、运行输出或文档。

| 目录（均位于 `examples/phase04/`） | 起始输入 | 实际模型路径与结果 | 模型请求／工具调用 |
| --- | --- | --- | --- |
| `real-normal/` | 完整 30 秒需求，无初稿 | 模型生成四镜脚本；规则检查指出未知文字后，模型多次修正并重新检查；最终修订 4，两项检查通过，估时 28.2 秒，`success` | 7／8 |
| `real-no-materials/` | 同一需求，受控空素材库 | 模型发出 4 次不同检索，均得到空结果；随后自行选择请求补充事实与限定，`needs_input`，没有脚本 | 4／5 |
| `real-overlong-repair/` | 同一需求，提供人工构造的超时草稿 | 模型先取得初稿 43.5 秒的实际估算，再重写文案和画面预算；修订 2 的规则检查通过，并重新估算为 24.0 秒，`success` | 5／6 |

工具总数包含 `finish_task`。调用数可以多于模型请求数，因为模型可以在一轮提出多个工具调用。工具按调用顺序执行，模型观察结果后才做下一轮选择。

### 正常路径中的实际修正

`real-normal/trace.json`：

- 事件 12：初版时长检查通过，估时 23.4 秒。
- 事件 17、22：后续稿件存在政策外文字，规则检查不通过。
- 模型在事件 20、25 的动作说明中分别提出调整标题、字幕及连接短语；程序没有代改文本。
- 事件 27：修订 4 的规则检查通过；事件 31：同一修订估时 28.2 秒，通过。
- 事件 35、36：模型的成功状态获准，运行结束。

这些失败是文案政策拦截，不应描述成已经证明模型编造了产品事实。记录体现模型根据具体反馈改写，但也展示了保守白名单造成的修改成本。

### 超时草稿的实际修正

`real-overlong-repair/trace.json`：

- 事件 2：注册提供的人工初稿，来源标为 `provided_input`，不是模型生成。
- 事件 11：模型选择估算初稿；事件 12：实际返回 43.5 秒，超出 30 秒上限。
- 事件 15：模型依据超时 13.5 秒的反馈选择重写并检查；事件 16：注册修订 2。
- 事件 17：新稿规则检查通过；事件 21：同一新稿估时 24.0 秒，通过。
- 事件 25、26：接受模型的成功状态并结束。

初稿三镜、新稿四镜，旁白、字幕和画面预算均发生变化。没有把第三步预设短稿当作真实模型修改结果。实际新稿可以在 `real-overlong-repair/script.md` 查看。

## 3. 离线执行边界验证

`mock-normal/` 固定执行正常示例，返回流程成功；`mock-step-limit/` 仅允许一次模型步骤，返回 `incomplete` 和“已达到模型决策步数上限”；`mock-tool-limit/` 仅允许一次工具调用，也明确返回未完成。两个上限示例各执行 1 次预设模型调用、1 次工具调用，未越界。

Mock 全部标记 `mode: mock`、`evidence_scope: scripted_flow_only`，其动作与草稿预设，不能作为真实模型决策证据。离线单元测试还覆盖批量调用中达到上限、旧检查失效、缺少来源、提前宣告成功、未知工具、坏 JSON、工具故障、模型连接失败等情况。

## 4. 复现

下列命令每次创建新输出目录；真实模式需要本地配置及可用接口：

```powershell
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --materials examples/agent_inputs/empty_materials.json
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json --initial-script examples/tool_inputs/overlong.json
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json --max-steps 1
python -m src.shortvideo_agent run --mode mock --input examples/inputs/normal.json --max-tool-calls 1
python -W error::ResourceWarning -m unittest discover -s tests -v
```

模型输出可能变化，且模型别名的后端版本可能调整，因此不承诺重跑得到完全相同的分镜、时长或调用次数。验收应检查实际输出及对应 Trace 的不变量。

## 5. 尚未完成的验证

缺少关键信息、工具故障的真实模型端到端处理、无依据产品结论的实际修改，以及固定其他条件时改变目标／检索结果后的动作对照，需要在第五步补齐。当前三条真实路径足以证明核心循环工作，不代表所有 A01—A07 已经验收完成。

## 6. 最终检查与阶段计时

最终离线回归 72 项全部通过：基础 16 项、业务工具 31 项、Agent 执行边界 22 项、保存证据审计 3 项。证据审计核对 JSON 契约、日志与 Trace 一致、调用计数与上限、最终检查与脚本指纹一致，并对成功稿件重新执行估时及规则检查。

对 70 个可提交文件进行真实密钥精确匹配，命中数为 0；`.env` 仍被 Git 忽略；实际输出中没有模型内部推理字段。未暂存、提交或推送。

本阶段记录区间：2026-10-28 12:25:05—12:36:55（Asia/Shanghai），11 分 50 秒，截至最终验证与敏感信息检查完成。包含编码、文档和真实运行，不包括前三步及最后交接文字，不代表项目总用时。
