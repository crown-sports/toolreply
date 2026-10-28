# toolreply：工具调用对话记录体检

工具调用两次、结果也返回两次，仍可能出错：两个结果可能都引用了第一个调用 ID。
toolreply 会定位重复结果和缺失结果，帮助你在回放记录或运行回归测试前发现问题。

这是本地 Python 命令行工具，不调用模型、不执行工具、不上传对话，没有运行时第三方依赖。
它检查记录里的配对和顺序，不证明工具执行成功或回答正确。

## 试用

需要 Python 3.10 及以上。克隆仓库后：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
toolreply check examples/openai-broken.json --format openai-chat
toolreply check examples/openai-fixed.json --format openai-chat
```

Windows PowerShell 激活环境用 `.venv\Scripts\Activate.ps1`。
第一个示例会报告 1 个重复结果、1 个缺失结果；第二个修正了结果 ID，报告 0 个错误。
示例均为人工构造，不会发出真实请求。也可从 GitHub Releases 下载 wheel 安装。
目前没有发布到 PyPI。

## 检查自己的记录

输入为完整 JSON 消息数组，或含 `messages` 数组的对象；格式必须明确指定。

```sh
toolreply check history.json --format openai-chat --output json
toolreply check history.json --format anthropic
```

- `openai-chat`：Chat Completions 的 function `tool_calls` 和 tool 消息。
- `anthropic`：客户端 `tool_use` 与用户消息内的 `tool_result`。
- 检查调用和结果 ID 缺失、重复、丢失、孤立、迟到、参数 JSON 不完整，以及结果顺序。
- 并行结果可以逆序返回；不同轮次重复 ID 记警告，按当前轮次配对。
- Anthropic 相邻同角色消息会合并检查，错误位置仍指向原文件。

记录正在生成时可加 `--allow-pending-tail`，只把最后一批尚未返回的结果降为警告。
中间漏掉结果、或用户已继续发言的情况仍然报错。

退出码：`0` 无错误；`1` 有错误；`2` 输入或命令错误。
加 `--warnings-as-errors` 可让警告也返回 `1`，方便 CI 使用。

报告只包含统计、诊断代码和 JSON Pointer 位置，不输出原始工具名、ID、参数或结果内容。
原始文件不会被修改，也不会被自动脱敏。

## 在 GitHub Actions 中检查回归样本

无需手动安装 toolreply；检出仓库后加入：

```yaml
- uses: crown-sports/toolreply@v0.2.0
  with:
    files: tests/fixtures/openai/**/*.json
    format: openai-chat
    warnings-as-errors: "true"
```

支持多行路径/glob；每个模式必须匹配文件，检查失败仍生成 JSON 报告。完整工作流、参数、
可选报告上传和本地复现见 [Action 使用说明](action.zh-CN.md)。需要固定依赖时使用发布版本的完整 commit SHA。

## 已知边界

当前不支持 Responses API、流式片段、旧版 function_call、Anthropic 服务端工具或程序化调用。
它不是完整请求格式验证器，不检查工具参数 Schema、权限、执行效果或回答质量。
0 个调用的报告不代表检查了工具流程。详细规则与依据见 [rules.md](rules.md)。

欢迎提交脱敏后的错误案例，尤其是合法对话被误报的情况。贡献流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
