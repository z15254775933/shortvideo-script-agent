# 交付与评审导航

题号：4，短视频脚本 Agent。当前为 0.2.0，新增创作模式及实际漏检修正；公开交付入口如下。

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

当前预期为 11/11 项保存样本验收、102 项离线测试通过；这两个命令不调用模型，也不需要真实密钥。创作模式重算确定性检查并核对已保存的模型审核，不将离线重放算作新的独立语义判断。

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

## 5. 交付状态与版本核对

- 首次交付已在无密钥独立目录和新虚拟环境中通过原 8 项审计与 81 项测试，记录为历史快照。
- 0.2.0 的新增样本、已发现漏检、测试及当前确定性防线见 `docs/08-improvements.md`。
- 仓库公开，分支 `main`；实际最终提交 SHA 由 Git 和交付回复提供。
- 真实密钥不进入提交，更新发布前再次核对暂存内容和本地／远端 SHA。

无密钥复核与仓库创建的实际记录见 [最终交付复核](07-final-verification.md)。最终提交与远端分支的精确 SHA 以 GitHub、`git rev-parse HEAD` 和交付回复为准。
