from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AbaqusMcpConfig
from .core import (
    abaqus_environment,
    extract_odb_summary,
    get_job_status,
    list_abaqus_files,
    read_abaqus_text_file,
    run_abaqus_script,
    submit_inp_job,
    terminate_job,
)


# FastMCP 会在导入时根据这些函数生成工具 schema。这里保持薄封装：
# 校验和 Abaqus 相关逻辑放在 core.py，便于不启动 MCP transport 也能测试。
config = AbaqusMcpConfig.from_env()
mcp = FastMCP("abaqus-mcp", json_response=True)


@mcp.tool()
def abaqus_env(probe: bool = True) -> dict[str, Any]:
    """检查 Abaqus 命令、工作区、允许目录，并可选探测 Abaqus 版本。"""
    return abaqus_environment(config, probe=probe)


@mcp.tool()
def list_files(
    directory: str | None = None,
    recursive: bool = False,
    extensions: list[str] | None = None,
    max_files: int = 200,
) -> dict[str, Any]:
    """列出工作区或允许目录下的 Abaqus 相关文件。"""
    return list_abaqus_files(
        config,
        directory=directory,
        recursive=recursive,
        extensions=extensions,
        max_files=max_files,
    )


@mcp.tool()
def read_text_file(path: str, max_bytes: int = 120_000, tail_lines: int | None = 120) -> dict[str, Any]:
    """读取或 tail Abaqus 文本文件，例如 .log、.sta、.msg、.dat、.inp、.py 或 .csv。"""
    return read_abaqus_text_file(
        config,
        path=path,
        max_bytes=max_bytes,
        tail_lines=tail_lines,
    )


@mcp.tool()
def submit_job(
    inp_path: str,
    job_name: str | None = None,
    workdir: str | None = None,
    cpus: int | None = None,
    memory: str | None = None,
    gpus: int | None = None,
    double_precision: bool = False,
    wait: bool = False,
    timeout_seconds: int = 3600,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """提交 Abaqus .inp 作业；默认后台启动，并返回状态文件路径。"""
    return submit_inp_job(
        config,
        inp_path=inp_path,
        job_name=job_name,
        workdir=workdir,
        cpus=cpus,
        memory=memory,
        gpus=gpus,
        double_precision=double_precision,
        wait=wait,
        timeout_seconds=timeout_seconds,
        extra_args=extra_args,
    )


@mcp.tool()
def job_status(job_name: str, workdir: str | None = None, include_tail: bool = True) -> dict[str, Any]:
    """解析 .lck、.log、.sta、.msg 和本地 registry，检查 Abaqus 作业状态。"""
    return get_job_status(config, job_name=job_name, workdir=workdir, include_tail=include_tail)


@mcp.tool()
def run_script(
    script_path: str,
    mode: str = "cae",
    workdir: str | None = None,
    script_args: list[str] | None = None,
    timeout_seconds: int = 3600,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """用 Abaqus 运行允许目录内的 Python 脚本；mode='cae' 使用 cae noGUI，mode='python' 使用 abaqus python。"""
    return run_abaqus_script(
        config,
        script_path=script_path,
        mode=mode,
        workdir=workdir,
        script_args=script_args,
        timeout_seconds=timeout_seconds,
        extra_env=extra_env,
    )


@mcp.tool()
def odb_summary(odb_path: str, step_name: str | None = None, timeout_seconds: int = 1800) -> dict[str, Any]:
    """用 abaqus python 打开 ODB，并摘要读取 step、instance、场输出、位移、应力和 PEEQ。"""
    return extract_odb_summary(
        config,
        odb_path=odb_path,
        step_name=step_name,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def terminate(job_name: str, workdir: str | None = None, timeout_seconds: int = 120) -> dict[str, Any]:
    """按作业名请求 Abaqus 终止正在运行的作业。"""
    return terminate_job(
        config,
        job_name=job_name,
        workdir=workdir,
        timeout_seconds=timeout_seconds,
    )


@mcp.resource("abaqus://workspace")
def workspace_resource() -> dict[str, Any]:
    """返回当前配置的 Abaqus MCP 工作区和允许访问目录。"""
    return {
        "workspace": str(config.workspace),
        "allowed_roots": [str(path) for path in config.allowed_roots],
        "registry_dir": str(config.registry_dir),
    }


@mcp.prompt()
def diagnose_failed_job(job_name: str, workdir: str | None = None) -> str:
    """生成用于诊断 Abaqus 失败作业的提示词模板。"""
    location = workdir or str(config.workspace)
    return (
        "请诊断位于 '%s' 的 Abaqus 作业 '%s'。"
        "先调用 job_status 并设置 include_tail=true，然后检查 .log、.sta、.msg 和 .dat 文件。"
        "请找出第一个失败标记，判断更可能是建模问题、收敛问题还是许可证问题，并给出最小修改建议。"
        % (location, job_name)
    )


def main() -> None:
    # stdio 是桌面 MCP 客户端的常规模式；环境变量切换主要用于本机
    # streamable-http 调试。
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
