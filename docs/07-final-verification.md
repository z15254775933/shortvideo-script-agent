# 最终交付复核

题号：4，短视频脚本 Agent。公开仓库：[z15254775933/shortvideo-script-agent](https://github.com/z15254775933/shortvideo-script-agent)，主分支 `main`。

最终提交 SHA 以交付回复、GitHub 分支记录或仓库中的 `git rev-parse HEAD` 输出为准；不在提交自身的文件里预填一个尚未生成的 SHA。

## 1. 独立环境复核

2026-10-28，将按 Git 忽略规则筛出的 110 个项目文件导出到另一个目录，导出不包含 `.env` 或 `.git`。随后用 Python 3.14.4 创建 `--without-pip` 虚拟环境，配置为 `include-system-site-packages = false`，并将子进程的 `DEEPSEEK_API_KEY` 置空。

使用虚拟环境的 Python、`-E` 参数和导出目录作为工作目录实际执行：

| 检查 | 实际结果 |
| --- | --- |
| `python -E -m src.shortvideo_agent evaluate` | 8/8 保存样本审计通过，新增模型调用 0 |
| `python -E -W error::ResourceWarning -m unittest discover -s tests -v` | 81 项全部通过 |
| 导出目录的 `.env` | 不存在 |
| 导出目录的 `.git` | 不存在 |
| 第三方运行时依赖 | 未安装，无需安装 |

该验证证明已保存的输入、数据与记录能在不同项目目录下离线核对，不依赖原目录中的密钥。它仍是同一台 Windows 机器、同一 Python 版本，不冒充跨系统测试或实际视频估时校准。

局部导出与虚拟环境位于被忽略的 `.verification/`，不属于公开提交内容。最终文档更新不改变业务实现、合成资料或归档运行产物。

## 2. 远端创建

提交者明确选择“新建，公开的”。浏览器自动化受限后，使用 Git 已有账号的官方授权流程完成认证，再通过 GitHub 官方 REST API 创建公开空仓库，实际返回 `private: false`、默认分支 `main`。

凭据由 Git Credential Manager 管理，API 请求只在内存中使用授权。GitHub 授权及 DeepSeek 密钥均不写入项目。随后以常规 Git 提交和推送交付项目，不创建额外 PR。

## 3. 提交内容核对

- 提交包含源码、测试、合成资料、输入样例、真实输出、Trace、AI 使用说明及复盘。
- 真实密钥文件与 `.verification/` 被 Git 忽略；暂存与提交前检查实际密钥匹配。
- 运行产物未为凑路径而手工改写；完整真实运行、Mock、预设草稿和单步对照在文档中分别说明。
- 提交者个人复核仍只按实际记录追加，AI 代执行的测试不改称个人独立验证。

## 4. 复现入口

```powershell
git clone https://github.com/z15254775933/shortvideo-script-agent.git
cd shortvideo-script-agent
python -m src.shortvideo_agent evaluate
python -W error::ResourceWarning -m unittest discover -s tests -v
git rev-parse HEAD
```

真实模型重跑需要评审者自己的本地配置，见 README；阅读已有证据、离线审计和单元测试不需要密钥。
