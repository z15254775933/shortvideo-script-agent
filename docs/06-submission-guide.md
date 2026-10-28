# 交付与评审导航

题号：4，短视频脚本 Agent。实现、样本验收、要求文档及无密钥独立环境复核已完成；公开交付入口如下。

| 提交信息 | 当前状态 |
| --- | --- |
| 题号 | 4 |
| 运行入口 | 仓库根目录的 `python -m src.shortvideo_agent` |
| GitHub URL | [z15254775933/shortvideo-script-agent](https://github.com/z15254775933/shortvideo-script-agent) |
| 最终 commit SHA | 执行 `git rev-parse HEAD` 读取；精确值在最终交付回复中提供 |
| 访问权限 | 按提交者选择创建公开仓库，默认分支 `main` |

## 1. 推荐评审顺序

1. 阅读 [README](../README.md)，确认运行方式、配置和边界。
2. 查看 [需求与验收](01-requirements.md)、[方案](02-solution.md)，核对范围及决策职责。
3. 运行离线评审，阅读 [评估说明](03-evaluation.md) 与 [机器报告](../examples/phase05/acceptance.actual.json)。
4. 对照 [超时改稿](../examples/phase04/real-overlong-repair/script.md) 及其 [Trace](../examples/phase04/real-overlong-repair/trace.json)，检查实际观察、改稿和同版本复查。
5. 阅读 [AI 使用说明](04-ai-usage.md)、[复盘](05-retrospective.md)，了解开发辅助范围与尚未验证的部分。

## 2. 无密钥评审

环境要求为 Python 3.11 或以上，实际验证环境为 Windows、Python 3.14.4。运行时无第三方依赖。在仓库根目录执行：

```powershell
python -m src.shortvideo_agent evaluate
python -W error::ResourceWarning -m unittest discover -s tests -v
```

当前预期为 8/8 项保存样本验收、81 项离线回归通过；这两个命令不调用模型，也不需要真实密钥。审计会核对日志与 Trace、版本与指纹、实际来源和执行上限，并重算成功稿件的检查。

## 3. 真实运行

按 `.env.example` 在本地填写自己的 DeepSeek 凭据，然后运行：

```powershell
python -m src.shortvideo_agent run --mode real --input examples/inputs/normal.json
```

真实重跑会产生新的调用、稿件和目录，不承诺与归档结果完全相同。完整模式、工具调用、初稿编辑及单步对照的命令见 README 和评估说明。

归档运行目录的 `script.md` 便于阅读；`result.json` 是结构化结果；`trace.json` 与 `events.jsonl` 是实际记录。编辑归档结果会使其与旧证据不一致；新的修改应重新运行或另存并验证。

## 4. 提交者可追加的个人复核记录

当前未确认提交者已经独立运行或修改代码。可以在实际操作后，将以下内容追加到 AI 使用说明：日期、使用的命令、观察到的状态、选取的 Trace 步骤、修改文件及复验结果。只记录确实做过的工作。

建议能说明：为什么模型看到不同工具结果会选择不同动作；为什么改稿后不能使用旧检查；为什么当前事实检查会误拦；为什么单步对照和 Mock 不等于完整真实运行。

## 5. 最终交付核对

- 已在仅含项目可提交文件、没有 `.env` 的独立目录和新虚拟环境中复核，8/8 审计及 81 项测试通过。
- 再次检查真实密钥与暂存内容，确保 `.env` 不进入提交。
- 确认最终 GitHub 仓库和可见性，创建真实提交并推送到确定的仓库。
- 记录题号、真实 GitHub URL 与最终 SHA，并确认评审账号能读取。

无密钥复核与仓库创建的实际记录见 [最终交付复核](07-final-verification.md)。最终提交与远端分支的精确 SHA 以 GitHub、`git rev-parse HEAD` 和交付回复为准。
