# Abaqus MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io/) server for running and inspecting Abaqus jobs from MCP-compatible clients.

The server wraps the local Abaqus command line and exposes focused tools for:

- inspecting the Abaqus environment;
- listing Abaqus-related files in an allowed workspace;
- reading `.log`, `.sta`, `.msg`, `.dat`, `.inp`, `.py`, and other text outputs;
- submitting `.inp` jobs;
- checking job status from Abaqus output files;
- running trusted Abaqus Python or CAE `noGUI` scripts;
- extracting a compact summary from `.odb` files with `abaqus python`;
- requesting job termination.

This project does not include Abaqus, Dassault Systemes files, example `.odb/.cae` outputs, or any Abaqus license. You must have a licensed Abaqus installation available on the machine running the server.

## Requirements

- Python 3.10 or newer.
- Abaqus installed locally and available through `abaqus` or a configured command such as `C:\SIMULIA\Commands\abaqus.bat`.
- An MCP client that can launch local stdio servers.

## Install

```powershell
git clone https://github.com/<your-user>/abaqus-mcp-server.git
cd abaqus-mcp-server
python -m pip install -r requirements.txt
python -m pip install -e .
```

Check that Abaqus can be found:

```powershell
Get-Command abaqus
```

If your installation only exposes a batch file, configure it with `ABAQUS_COMMAND`.

## Start Locally

Set a workspace containing your Abaqus input/output files, then start the server:

```powershell
$env:ABAQUS_MCP_WORKSPACE="C:\path\to\abaqus-workspace"
$env:ABAQUS_COMMAND="C:\SIMULIA\Commands\abaqus.bat"
python -m abaqus_mcp.server
```

The default transport is `stdio`, which is the normal mode for local MCP clients.

For HTTP debugging:

```powershell
$env:MCP_TRANSPORT="streamable-http"
python -m abaqus_mcp.server
```

## MCP Client Configuration

Copy `mcp_config.example.json` and adjust the paths for your machine:

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

To allow additional directories, set `ABAQUS_MCP_ALLOWED_DIRS`. Use the platform path separator, for example `;` on Windows.

## Tools

| Tool | Purpose |
| --- | --- |
| `abaqus_env` | Check workspace, allowed roots, Abaqus command, Python version, and optionally probe Abaqus release. |
| `list_files` | List Abaqus-related files under an allowed directory. |
| `read_text_file` | Read or tail allowed text output files. |
| `submit_job` | Submit an Abaqus `.inp` job. Supports async and wait modes. |
| `job_status` | Parse `.lck`, `.log`, `.sta`, `.msg`, and registry metadata. |
| `run_script` | Run a trusted Python script with `abaqus cae noGUI=<script>` or `abaqus python <script>`. |
| `odb_summary` | Run a bundled Abaqus Python helper to summarize an `.odb`. |
| `terminate` | Request `abaqus terminate job=<name>`. |

## Example Tool Payloads

Submit an input file asynchronously:

```json
{
  "inp_path": "Job_A.inp",
  "job_name": "Job_A_mcp",
  "cpus": 4,
  "wait": false
}
```

Check status:

```json
{
  "job_name": "Job_A_mcp",
  "include_tail": true
}
```

Run a trusted Abaqus script:

```json
{
  "script_path": "scripts/build_model.py",
  "mode": "cae",
  "timeout_seconds": 3600
}
```

Extract a compact ODB summary:

```json
{
  "odb_path": "Job_A_mcp.odb"
}
```

## Security Model

The server is intended for local, trusted use.

- File access is restricted to `ABAQUS_MCP_WORKSPACE` and optional `ABAQUS_MCP_ALLOWED_DIRS`.
- Paths are resolved before use and rejected if they escape allowed roots.
- Abaqus commands are built as argument lists, not arbitrary shell strings.
- `submit_job.extra_args` accepts only simple Abaqus option syntax.
- `run_script` can execute Python code inside allowed directories. Only connect trusted MCP clients and only allow trusted workspaces.

Do not expose this server to untrusted networks or untrusted users.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ABAQUS_MCP_WORKSPACE` | current working directory | Main allowed workspace. |
| `ABAQUS_MCP_ALLOWED_DIRS` | empty | Extra allowed roots separated by `os.pathsep`. |
| `ABAQUS_COMMAND` | `abaqus` if found, otherwise common Windows Abaqus batch path | Abaqus executable or batch file. |
| `ABAQUS_MCP_REGISTRY_DIR` | `<workspace>/.abaqus_mcp` | Job registry and helper output directory. |
| `ABAQUS_MCP_MAX_CAPTURE_BYTES` | `200000` | Max captured stdout/stderr characters returned by tools. |
| `MCP_TRANSPORT` | `stdio` | MCP transport passed to FastMCP. |

## Tests

Core tests do not require a real Abaqus launch:

```powershell
python -m pytest
```

## License

MIT. See `LICENSE`.
