# 0.2.0 创作模式的实际记录

当前主验收报告：[final-acceptance.actual.json](final-acceptance.actual.json)。`acceptance.actual.json` 是第一次扩展到 11 项时的中间报告，当时 A08 仍指向首次创作样本。

| 目录 | 原始运行状态 | 当前用途 |
| --- | --- | --- |
| `creative-douyin/` | success，22.7 秒 | 首次自由文案样本，保留对照 |
| `creative-bilibili/` | success，25.3 秒 | A09，解释型主样本 |
| `creative-semantic-repair/` | success，22.4 秒 | 保留审核格式失败及后续恢复，不作为有效语义驳回证据 |
| `creative-semantic-repair-valid/` | success，26.3 秒 | A10，事件 6 实际语义驳回后改稿复查 |
| `creative-douyin-compact/` | 当时 success，26.0 秒 | **已确认漏检反例**：原审核放过“无需重剪”类推论，当前检查会拒绝，不计入通过主样本 |
| `creative-douyin-final/` | success，25.8 秒 | A08，增加工作流承诺防线后重新生成的最终主样本 |

每条完整运行都保留原始 `result.json`、`trace.json`、`events.jsonl` 与 `script.md`。没有手工将旧运行的成功改成失败来消除漏检历史。每个 Trace 中的审核记录是任务内部请求，不额外计为完整 Agent 运行。

过程、调用量及剩余限制见 [优化说明](../../docs/08-improvements.md)。
