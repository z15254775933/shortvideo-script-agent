# 第二步：项目骨架验证

日期：2026-10-28（Asia/Shanghai）。状态：基础检查通过，业务验收仍待执行。

本阶段记录的工作区间：11:39:11—11:45:42，共 6 分 31 秒，从本轮现状检查之后起计，包含编码、文档与验证。此段不包含此前讨论、第一步及最初连接预检，也不代表整个项目总用时。

## 实际环境与结果

环境为 Windows PowerShell、Python 3.14.4。项目没有第三方运行时依赖。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| CLI 入口与帮助 | 可运行，列出 `inspect`、`check-model`、`schema` | `python -m src.shortvideo_agent --help` |
| 正常输入与素材读取 | `ready`；读取 P01、P02 两条素材、两条事实及三条规则 | `examples/phase02/normal-inspection.actual.json` |
| 缺少目标时长 | `needs_input`；缺失字段为 `target_duration_seconds` | `examples/phase02/missing-duration-inspection.actual.json` |
| 离线模型诊断 | 固定 `OK`；标明 Mock、脚本化及仅验证流程 | `examples/phase02/mock-check.actual.json` |
| 项目真实模型诊断 | `deepseek-flash` 返回 `OK`，`finish_reason: stop`；实际输入 9 tokens、输出 1 token | `examples/phase02/deepseek-check.actual.json` |
| 基础测试 | 16 项通过，涵盖无效输入、重复 ID、配置、离线模式、模型响应、错误脱敏及输出保护 | `python -m unittest discover -s tests -v` |
| 最终资源检查 | 将资源警告视为错误后，16 项测试仍全部通过 | `python -W error::ResourceWarning -m unittest discover -s tests -v` |
| 退出码 | 缺少时长的 Python 进程返回 `2`，符合需要补充信息的约定 | PowerShell 运行检查后用 `exit $LASTEXITCODE` 保留原始退出码 |
| 凭据与 Git 检查 | 对 24 个可提交文件做实际密钥精确匹配，命中数为 0；`.env` 被忽略；尚无已跟踪文件或提交 | `git ls-files --cached --others --exclude-standard`、`git check-ignore .env` 及本地只输出匹配文件名的检查 |

真实模型诊断由项目 Python 适配器发起，并非复用此前 PowerShell 连接测试的结果；真实输出保存了 UTC 时间戳。以上实际输出均由 CLI 写入文件，未手工伪造成功结果。

首次基础测试在受限沙箱中因系统临时目录权限产生 6 项错误；允许访问临时目录后，同一测试命令全部通过。临时目录访问是测试所需的环境权限，并不是业务修复或模型故障恢复证据。最终测试代码使用占位凭据，不读取真实密钥，也不调用网络。

## 证据范围和已知限制

- 输入检查没有进行素材检索，也没有生成或评估脚本。
- 真实模型诊断只证明认证和基础文本请求可用；工具调用往返和动态决策尚未实测。
- 对模型工具调用格式的测试使用固定响应夹具，仅验证适配器解析及字段保留。
- 时长、品牌规则、事实支持、旧版本检查结果失效和执行上限尚未实现。
- 业务验收用例 A01—A07 均保持待执行；这里的四份输出不能计为最终要求的三组业务输入输出和 Trace。
- 尚未进行打包安装、其他 Python 版本、其他系统或不同模型的验证。
