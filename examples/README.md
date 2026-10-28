# 样例与验证材料索引

主验收映射为 `data/evaluation_cases.json`，当前 11 项机器报告为 [final-acceptance.actual.json](phase06/final-acceptance.actual.json)，完整说明见 [评估文档](../docs/03-evaluation.md)。`phase05/acceptance.actual.json` 保留原 8 项基线。

## 输入与来源

- `inputs/`：创作需求，含完整输入、缺少时长、十秒目标、先审稿请求。
- `agent_inputs/`：受控的空素材库与仅 P01 的合成素材库。
- `tool_inputs/`：开发阶段预先构造、由 AI 助手编写的脚本夹具；不是业务 Agent 在线自主生成的结果，也不证明提交者手写过这些初稿。
- 正常资料及品牌规则位于 `data/`，明确标注为合成资料。

## 实际产物的范围

| 位置 | 内容 | 证据边界 |
| --- | --- | --- |
| `phase02/` | 四份输入／连接诊断输出 | 不证明完整脚本生成；其中 Mock 有明确标识 |
| `phase03/` | 八份独立业务工具实际输出 | 证明工具行为，不证明模型会调整动作 |
| `phase04/real-*` | 正常、无素材、超时改稿三次完整真实模型运行 | 完整结果、脚本、Trace 和事件日志 |
| `phase04/mock-*` | 三条预设的完整离线流程 | 不计为真实模型决策效果 |
| `phase05/real-*` | 六次完整真实模型运行，覆盖缺失信息、检索故障、效果数字修正及两个执行上限 | 全部记录保留，含普通请求下主动删去数字的补充样本 |
| `phase05/retrieval-comparison/` | 共享前缀后两个新增的真实下一步决策 | 已有首轮选择被重放；新动作未执行，不是两次完整任务 |
| `phase06/` | 六条完整真实创作运行：首试、B站、格式失败恢复、有效语义修正、一次审核漏检、最终抖音稿 | 审核漏检记录不列为通过样本；详情见本轮优化文档 |

完整运行共归档 15 次真实流程、3 次 Mock 流程。单步对照另含 2 次新模型请求，不加入完整任务数量。新增独立审核是任务内部的模型请求，不额外计为完整任务。

## 当前推荐入口

- [抖音最终稿](phase06/creative-douyin-final/script.md)：25.8 秒，可拍摄的情境开场与逐镜时间轴。
- [B站解释稿](phase06/creative-bilibili/script.md)：25.3 秒，区分已知事实和资料未覆盖能力。
- [有效语义驳回后修正](phase06/creative-semantic-repair-valid/script.md)：26.3 秒，初稿来源与事件 6 的驳回均保留。
- [审核漏检反例](phase06/creative-douyin-compact/script.md)：原始运行曾为 success，当前检查会拒绝“无需重剪”类推论，不计入通过展示。

## 原版核心证据

- [正常成稿](phase04/real-normal/script.md)：28.2 秒，来源 P01／P02。
- [超时改稿](phase04/real-overlong-repair/script.md)：提供的初稿经真实估时为 43.5 秒，模型改稿后 24.0 秒。
- [无依据数字修正](phase05/real-unsupported-reviewed/script.md)：仅 P01“支持字幕”，先检查再修正，最后 21.9 秒；初稿的数字不能归因成模型自主生成。

对应目录中的 JSON 及日志由 CLI 实际保存，后续没有为凑验收路径手工修改。`phase05/evaluation.actual.json` 和该阶段 `acceptance.actual.json` 是基线报告；当前以 `phase06/final-acceptance.actual.json` 为准，迭代中的失败记录见 [phase06 索引](phase06/README.md)。
