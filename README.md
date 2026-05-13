# Abaqus MCP Server

一个用于本地调用 Abaqus 的 [Model Context Protocol](https://modelcontextprotocol.io/) 服务器。它的定位很简单：让 MCP 客户端能安全地提交 Abaqus 作业、查看日志、读取结果文件，并对 `.odb` 做轻量摘要。

This is a local MCP server for running and inspecting Abaqus jobs from MCP-compatible clients.

> 说明：本项目不包含 Abaqus、本构模型、Dassault Systemes 文件、示例 `.odb/.cae` 结果或任何许可证。使用前需要你自己的合法 Abaqus 安装和许可证。

## 功能特性

- 检查 Abaqus 环境、工作区和允许访问的目录。
- 列出工作区内的 Abaqus 相关文件。
- 读取或 tail `.log`、`.sta`、`.msg`、`.dat`、`.inp`、`.py` 等文本文件。
- 提交 `.inp` 作业，支持同步等待或后台运行。
- 根据 `.lck/.log/.sta/.msg` 判断作业状态。
- 运行可信的 Abaqus Python 或 CAE `noGUI` 脚本。
- 使用 `abaqus python` 提取 `.odb` 的简要信息。
- 调用 `abaqus terminate job=<name>` 终止作业。

## 适用场景

这个 server 适合这些工作流：

- 让 Codex、Claude Desktop 或其他 MCP 客户端帮你提交 Abaqus 作业。
- 快速查看 `.sta/.msg/.log` 中的收敛失败原因。
- 在不手动打开 Abaqus/CAE 的情况下，对 `.odb` 做第一轮摘要检查。
- 把参数化建模脚本、提交、结果检查串成半自动流程。

它不适合直接暴露到公网，也不适合连接不可信的 MCP 客户端。

## 环境要求

- Python 3.10 或更高版本。
- 本机已安装 Abaqus，并且可以通过 `abaqus` 或类似 `C:\SIMULIA\Commands\abaqus.bat` 的命令启动。
- 一个可以启动本地 stdio MCP server 的 MCP 客户端。

## 安装

```powershell
git clone https://github.com/<your-user>/abaqus-mcp-server.git
cd abaqus-mcp-server
python -m pip install -r requirements.txt
python -m pip install -e .
```

检查 Abaqus 命令是否可用：

```powershell
Get-Command abaqus
```

如果你的机器只能通过 batch 文件启动 Abaqus，可以后面用 `ABAQUS_COMMAND` 指定。

## 本地启动

先设置 Abaqus 工作区。这个目录会作为默认安全边界，MCP 客户端只能访问这个目录和显式允许的额外目录。

```powershell
$env:ABAQUS_MCP_WORKSPACE="C:\path\to\abaqus-workspace"
$env:ABAQUS_COMMAND="C:\SIMULIA\Commands\abaqus.bat"
python -m abaqus_mcp.server
```

默认传输方式是 `stdio`，适合 MCP 客户端本地调用。

如果要做 HTTP 调试：

```powershell
$env:MCP_TRANSPORT="streamable-http"
python -m abaqus_mcp.server
```

也可以使用仓库里的启动脚本：

```powershell
.\start_abaqus_mcp.ps1
```

## MCP 客户端配置

复制 `mcp_config.example.json`，然后按你的机器修改路径：

```json
{
  "mcpServers": {
    "abaqus": {
      "command": "python",
      "args": ["-m", "abaqus_mcp.server"],
      "cwd": "C:\\path\\to\\abaqus-mcp-server",
      "env": {
        "ABAQUS_MCP_WORKSPACE": "C:\\path\\to\\abaqus-workspace",
        "ABAQUS_COMMAND": "C:\\SIMULIA\\Commands\\abaqus.bat"
      }
    }
  }
}
```

如果需要允许访问额外目录，设置 `ABAQUS_MCP_ALLOWED_DIRS`。Windows 下多个目录用分号分隔。

## MCP 工具

| 工具 | 作用 |
| --- | --- |
| `abaqus_env` | 检查工作区、允许目录、Abaqus 命令、Python 版本，并可选探测 Abaqus release。 |
| `list_files` | 列出允许目录下的 Abaqus 相关文件。 |
| `read_text_file` | 读取或 tail Abaqus 文本文件。 |
| `submit_job` | 提交 Abaqus `.inp` 作业，支持后台和同步模式。 |
| `job_status` | 解析 `.lck/.log/.sta/.msg` 和本地 registry，判断作业状态。 |
| `run_script` | 用 `abaqus cae noGUI=<script>` 或 `abaqus python <script>` 运行可信脚本。 |
| `odb_summary` | 调用内置 helper，用 Abaqus Python 摘要读取 `.odb`。 |
| `terminate` | 请求终止指定 Abaqus 作业。 |

## 示例调用

提交一个 `.inp` 作业：

```json
{
  "inp_path": "Job_A.inp",
  "job_name": "Job_A_mcp",
  "cpus": 4,
  "wait": false
}
```

查询作业状态：

```json
{
  "job_name": "Job_A_mcp",
  "include_tail": true
}
```

运行建模脚本：

```json
{
  "script_path": "scripts/build_model.py",
  "mode": "cae",
  "timeout_seconds": 3600
}
```

提取 ODB 摘要：

```json
{
  "odb_path": "Job_A_mcp.odb"
}
```

## 安全边界

这个项目默认按“本地可信工具”设计，但仍做了几层限制：

- 文件访问限制在 `ABAQUS_MCP_WORKSPACE` 和 `ABAQUS_MCP_ALLOWED_DIRS` 内。
- 所有路径会先解析，再检查是否逃逸允许目录。
- Abaqus 命令使用参数列表构造，不提供任意 shell 命令入口。
- `submit_job.extra_args` 只接受简单 Abaqus 选项格式，例如 `ask_delete=OFF`。
- `run_script` 会执行允许目录内的 Python 脚本，因此只能连接可信客户端、运行可信脚本。

不要把这个 server 直接暴露给公网或不可信用户。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ABAQUS_MCP_WORKSPACE` | 当前工作目录 | 主工作区，也是默认允许访问目录。 |
| `ABAQUS_MCP_ALLOWED_DIRS` | 空 | 额外允许访问目录，按 `os.pathsep` 分隔。 |
| `ABAQUS_COMMAND` | 优先找 `abaqus`，否则使用常见 Windows Abaqus batch 路径 | Abaqus 可执行命令或 batch 文件。 |
| `ABAQUS_MCP_REGISTRY_DIR` | `<workspace>/.abaqus_mcp` | 作业 registry 和 helper 输出目录。 |
| `ABAQUS_MCP_MAX_CAPTURE_BYTES` | `200000` | 工具返回 stdout/stderr 的最大字符数。 |
| `MCP_TRANSPORT` | `stdio` | 传给 FastMCP 的 transport。 |

## 测试

核心测试不需要真实启动 Abaqus：

```powershell
python -m pytest
```

## English Quick Start

Install:

```powershell
git clone https://github.com/<your-user>/abaqus-mcp-server.git
cd abaqus-mcp-server
python -m pip install -r requirements.txt
python -m pip install -e .
```

Run:

```powershell
$env:ABAQUS_MCP_WORKSPACE="C:\path\to\abaqus-workspace"
$env:ABAQUS_COMMAND="C:\SIMULIA\Commands\abaqus.bat"
python -m abaqus_mcp.server
```

The server exposes tools for environment checks, file listing, log reading, job submission, job status inspection, trusted script execution, ODB summaries, and job termination. It is intended for local trusted use only.

## License

MIT. See `LICENSE`.
