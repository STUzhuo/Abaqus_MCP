from __future__ import annotations

from pathlib import Path

import pytest

from abaqus_mcp.config import AbaqusMcpConfig
from abaqus_mcp.core import (
    AbaqusMcpError,
    ensure_allowed_path,
    get_job_status,
    list_abaqus_files,
    read_abaqus_text_file,
    submit_inp_job,
    validate_extra_abaqus_args,
    validate_job_name,
)


def make_config(tmp_path: Path) -> AbaqusMcpConfig:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return AbaqusMcpConfig(
        workspace=workspace,
        allowed_roots=(workspace,),
        abaqus_command="abaqus",
        registry_dir=workspace / ".abaqus_mcp",
    )


def test_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    outside = tmp_path / "outside.inp"
    outside.write_text("*Heading\n", encoding="utf-8")

    with pytest.raises(AbaqusMcpError):
        ensure_allowed_path(outside, config, must_exist=True)


def test_lists_and_tails_abaqus_files(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    inp = config.workspace / "Job_A.inp"
    log = config.workspace / "Job_A.log"
    inp.write_text("*Heading\n", encoding="utf-8")
    log.write_text("line1\nline2\nline3\n", encoding="utf-8")

    listed = list_abaqus_files(config, extensions=[".inp", ".log"])
    assert listed["count"] == 2
    assert {item["name"] for item in listed["files"]} == {"Job_A.inp", "Job_A.log"}

    read = read_abaqus_text_file(config, path=str(log), tail_lines=2)
    assert read["content"] == "line2\nline3"


def test_job_status_completed_from_sta_and_log(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    (config.workspace / "Job_A.sta").write_text(
        "   1     1   1     0     3     3  0.0200     0.0200     0.02000\n"
        " THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n",
        encoding="utf-8",
    )
    (config.workspace / "Job_A.log").write_text("Abaqus JOB Job_A COMPLETED\n", encoding="utf-8")

    status = get_job_status(config, job_name="Job_A", include_tail=True)
    assert status["status"] == "completed"
    assert status["progress"]["step"] == 1
    assert status["progress"]["increment"] == 1


def test_job_status_failed_from_error_marker(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    (config.workspace / "Job_B.log").write_text(
        "Abaqus Error: Analysis Input File Processor exited with an error.\n",
        encoding="utf-8",
    )

    status = get_job_status(config, job_name="Job_B")
    assert status["status"] == "failed"
    assert any("error marker" in reason for reason in status["reasons"])


def test_job_name_validation() -> None:
    assert validate_job_name("Job_001-valid.name") == "Job_001-valid.name"
    with pytest.raises(AbaqusMcpError):
        validate_job_name("bad/name")
    with pytest.raises(AbaqusMcpError):
        validate_job_name("bad&name")


def test_extra_abaqus_args_are_restricted() -> None:
    assert validate_extra_abaqus_args(["ask_delete=OFF", "scratch=C:/temp"]) == [
        "ask_delete=OFF",
        "scratch=C:/temp",
    ]
    with pytest.raises(AbaqusMcpError):
        validate_extra_abaqus_args(["ask_delete=OFF & del important.txt"])
    with pytest.raises(AbaqusMcpError):
        validate_extra_abaqus_args(["../bad"])


def test_submit_wait_builds_foreground_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)
    inp = config.workspace / "Job_C.inp"
    inp.write_text("*Heading\n", encoding="utf-8")

    def fake_run(config_arg, args, *, cwd, timeout_seconds, extra_env=None):
        assert config_arg is config
        assert cwd == config.workspace
        assert "interactive" in args
        assert "job=Job_C" in args
        assert any(arg.startswith("input=") for arg in args)
        return {
            "command": ["abaqus"] + args,
            "cwd": str(cwd),
            "return_code": 0,
            "timed_out": False,
            "elapsed_seconds": 0.1,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr("abaqus_mcp.core.run_abaqus_foreground", fake_run)
    result = submit_inp_job(config, inp_path=str(inp), wait=True, cpus=2)
    assert result["job_name"] == "Job_C"
    assert result["return_code"] == 0
