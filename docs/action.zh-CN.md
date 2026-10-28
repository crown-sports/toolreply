# 用 GitHub Actions 检查已保存的对话

[English](action.md)

把人工构造或已脱敏的对话作为回归测试样本提交到仓库，Action 会在 CI 中检查工具调用与结果
是否正确配对。一次可检查多个文件，但必须明确选择同一种格式；它不会回放工具或调用模型 API。

```yaml
name: recorded histories
on: [push, pull_request]
permissions:
  contents: read
jobs:
  toolreply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
      - uses: crown-sports/toolreply@v0.2.0
        id: histories
        with:
          files: |
            tests/fixtures/openai/**/*.json
            tests/regressions/retry-history.json
          format: openai-chat
          warnings-as-errors: "true"
      # 可选：检查失败后也保存报告；不会上传原始对话。
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: ${{ always() && steps.histories.outputs.report-path != '' }}
        with:
          name: toolreply-report
          path: ${{ steps.histories.outputs.report-path }}
```

把示例路径改成仓库内实际存在的文件。需要固定依赖时，把 `@v0.2.0` 换成已审核发布版本的完整
commit SHA。无需 Marketplace 上架、API token、额外仓库或手动安装 toolreply。

## 参数与失败规则

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `files` | 必填 | 相对于 `GITHUB_WORKSPACE` 的路径或 glob，每行一个。 |
| `format` | 必填 | 只能是 `openai-chat` 或 `anthropic`，不自动猜测。混合格式请分两步检查。 |
| `allow-pending-tail` | `"false"` | 为 `"true"` 时，仅最后一批尚未完成的调用降为警告。 |
| `warnings-as-errors` | `"false"` | 为 `"true"` 时，警告也使步骤失败。 |

布尔值只接受 `true` 和 `false`，建议在 YAML 中加引号。路径在所有系统上都使用 `/` 分隔符。
支持 Python `pathlib` 的 `*`、`?`、字符组、递归 `**`，不执行 shell，不支持花括号展开或
gitignore 排除语法。每个非空行都必须匹配到文件，拼错路径不会静默通过。多行值内部的文件名
无需再加引号；保留行内空格，忽略空行。重复匹配同一个实际文件只检查一次。

不允许绝对路径、`..`、反斜杠或解析后指向工作区外的路径。工作区内部的符号链接可指向内部
文件，但不能越界。目录不能作为对话输入。文件名含换行时可用 glob 匹配，不能直接写成多行路径。

`0` 表示通过；`1` 表示发现错误或严格模式下的警告；`2` 表示参数、匹配或文件输入错误。
一个路径有问题时，仍检查其他已匹配文件。需要观察而不阻止 CI 时，由调用方设置 `continue-on-error`。
Action 通过官方 `setup-python` 固定使用 Python 3.12，不改变调用方的 Python 选择。

## 报告与隐私

输出 `report-path` 指向 `RUNNER_TEMP` 内每次调用独有的 JSON 文件。`files`、`errors`、
`warnings`、`input-errors` 分别是已检查文件数、错误数、警告数、输入/配置错误数。
检查失败也会先写报告和输出；Python 启动或临时目录写入失败时可能没有报告。
Action 不自动上传报告，上面的上传步骤可自行删除。

报告包含 `action_schema_version: 1`、工具版本、汇总、配置错误，以及逐文件的相对路径、
退出码和原 CLI JSON 报告（`schema_version: 1`）。配置错误用非空行的一基序号定位，
不回显原始模式。报告不包含对话里的工具名、调用 ID、参数、消息或结果正文；但文件名本身可能
包含敏感信息，启用上传前请检查 artifact 的可见范围和保留时间。

控制台和任务摘要只输出计数，避免恶意文件名被解释为工作流命令或 Markdown。
含 0 个受支持调用的文件会明确提示；通过检查不代表符合完整 API Schema，也不证明工具实际执行过。

## 本地复现与运行边界

Action 用 `python -I -S` 启动自身仓库中的适配器，只导入该 Action 版本里的 `src`，调用同一份
CLI 解析与检查逻辑，保留每文件 16 MiB 的限制。不安装 PyPI 包、不导入调用方仓库的 Python 模块，
也不依赖调用方当前目录定位代码。初始化 Python 可能需要下载运行时；检查过程完全离线。

在本仓库运行适配器测试，无需安装 toolreply：

```sh
python -m unittest discover -s tests -p test_action.py -v
```

测试覆盖多文件、重复/未匹配模式、特殊文件名、越界符号链接、失败报告、隐私和恶意同名 Python
模块。工作流在 GitHub 托管的 Ubuntu、Windows、macOS 上直接调用本地 Action，检查通过、失败、
未完成尾批和无效 JSON。Windows 不支持换行/冒号文件名，该测试仅在 Linux/macOS 运行；
本地系统禁止创建符号链接时，对应测试会明确跳过。自托管 runner 需满足 Bash 和官方
`setup-python` 的环境要求。完整实现依据和输出说明见 [英文文档](action.md)。
