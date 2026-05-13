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


config = AbaqusMcpConfig.from_env()
mcp = FastMCP("abaqus-mcp", json_response=True)


@mcp.tool()
def abaqus_env(probe: bool = True) -> dict[str, Any]:
    """Check Abaqus command, workspace, allowed roots, and optional Abaqus release probe."""
    return abaqus_environment(config, probe=probe)


@mcp.tool()
def list_files(
    directory: str | None = None,
    recursive: bool = False,
    extensions: list[str] | None = None,
    max_files: int = 200,
) -> dict[str, Any]:
    """List Abaqus-related files under the configured workspace or an allowed directory."""
    return list_abaqus_files(
        config,
        directory=directory,
        recursive=recursive,
        extensions=extensions,
        max_files=max_files,
    )


@mcp.tool()
def read_text_file(path: str, max_bytes: int = 120_000, tail_lines: int | None = 120) -> dict[str, Any]:
    """Read or tail a text Abaqus file such as .log, .sta, .msg, .dat, .inp, .py, or .csv."""
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
    """Submit an Abaqus .inp job. By default it starts asynchronously and returns status paths."""
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
    """Inspect an Abaqus job by parsing .lck, .log, .sta, .msg, and known registry metadata."""
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
    """Run an allowed Python script with Abaqus: mode='cae' uses cae noGUI, mode='python' uses abaqus python."""
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
    """Open an ODB with abaqus python and summarize steps, instances, fields, displacement, stress, and PEEQ."""
    return extract_odb_summary(
        config,
        odb_path=odb_path,
        step_name=step_name,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def terminate(job_name: str, workdir: str | None = None, timeout_seconds: int = 120) -> dict[str, Any]:
    """Request Abaqus to terminate a running job by name."""
    return terminate_job(
        config,
        job_name=job_name,
        workdir=workdir,
        timeout_seconds=timeout_seconds,
    )


@mcp.resource("abaqus://workspace")
def workspace_resource() -> dict[str, Any]:
    """Return the configured Abaqus MCP workspace and allowed roots."""
    return {
        "workspace": str(config.workspace),
        "allowed_roots": [str(path) for path in config.allowed_roots],
        "registry_dir": str(config.registry_dir),
    }


@mcp.prompt()
def diagnose_failed_job(job_name: str, workdir: str | None = None) -> str:
    """Prompt template for diagnosing a failed Abaqus job using this server."""
    location = workdir or str(config.workspace)
    return (
        "Diagnose the Abaqus job named '%s' in '%s'. "
        "First call job_status with include_tail=true, then inspect .log, .sta, .msg, and .dat files. "
        "Identify the first failure marker, likely modeling or license cause, and propose the smallest next fix."
        % (job_name, location)
    )


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
