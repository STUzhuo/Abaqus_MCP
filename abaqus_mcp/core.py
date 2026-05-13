from __future__ import annotations

import json
import locale
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import AbaqusMcpConfig


TEXT_EXTENSIONS = {
    ".com",
    ".csv",
    ".dat",
    ".env",
    ".inp",
    ".ipm",
    ".jnl",
    ".json",
    ".log",
    ".msg",
    ".py",
    ".rpy",
    ".sta",
    ".txt",
}

ABAQUS_EXTENSIONS = {
    ".cae",
    ".com",
    ".dat",
    ".inp",
    ".ipm",
    ".jnl",
    ".log",
    ".msg",
    ".odb",
    ".prt",
    ".py",
    ".sim",
    ".sta",
}

JOB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
EXTRA_ARG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:=(?:[A-Za-z0-9_.:+,/%-]+))?$")
STA_PROGRESS_RE = re.compile(
    r"^\s*(?P<step>\d+)\s+(?P<inc>\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+"
    r"(?P<total_time>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s+"
    r"(?P<step_time>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)",
    re.MULTILINE,
)


class AbaqusMcpError(ValueError):
    """Raised for user-correctable MCP tool errors."""


@dataclass(frozen=True)
class AbaqusPaths:
    job_name: str
    workdir: Path

    def for_extension(self, extension: str) -> Path:
        extension = extension if extension.startswith(".") else "." + extension
        return self.workdir / (self.job_name + extension)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_path_text(path: Path) -> str:
    return str(path.resolve())


def is_under(path: Path, root: Path) -> bool:
    try:
        path_norm = os.path.normcase(os.path.abspath(str(path)))
        root_norm = os.path.normcase(os.path.abspath(str(root)))
        return os.path.commonpath([path_norm, root_norm]) == root_norm
    except ValueError:
        return False


def ensure_allowed_path(
    value: str | os.PathLike[str],
    config: AbaqusMcpConfig,
    *,
    base: Path | None = None,
    must_exist: bool = False,
    allowed_extensions: set[str] | None = None,
    require_file: bool = False,
    require_dir: bool = False,
) -> Path:
    raw = Path(value).expanduser()
    path = raw if raw.is_absolute() else (base or config.workspace) / raw
    path = path.resolve(strict=False)

    if not any(is_under(path, root) for root in config.allowed_roots):
        roots = ", ".join(str(root) for root in config.allowed_roots)
        raise AbaqusMcpError(f"Path is outside allowed roots: {path}. Allowed roots: {roots}")

    if must_exist and not path.exists():
        raise AbaqusMcpError(f"Path does not exist: {path}")
    if require_file and path.exists() and not path.is_file():
        raise AbaqusMcpError(f"Path is not a file: {path}")
    if require_dir and path.exists() and not path.is_dir():
        raise AbaqusMcpError(f"Path is not a directory: {path}")

    if allowed_extensions is not None and path.suffix.lower() not in allowed_extensions:
        expected = ", ".join(sorted(allowed_extensions))
        raise AbaqusMcpError(f"Unsupported file extension for {path}. Expected one of: {expected}")

    return path


def validate_job_name(job_name: str) -> str:
    if not JOB_NAME_RE.match(job_name):
        raise AbaqusMcpError(
            "Invalid Abaqus job name. Use only letters, numbers, underscore, dash, and dot."
        )
    if job_name in {".", ".."}:
        raise AbaqusMcpError("Invalid Abaqus job name.")
    return job_name


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"... <truncated {omitted} chars>\n{text[-max_chars:]}"


def tail_text_file(path: Path, *, max_bytes: int = 80_000, tail_lines: int | None = None) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if max_bytes > 0 and size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
        data = handle.read()
    text = decode_bytes(data)
    if tail_lines is not None and tail_lines > 0:
        lines = text.splitlines()
        text = "\n".join(lines[-tail_lines:])
    return text


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object is not JSON serializable: {type(value)!r}")


def _registry_file(config: AbaqusMcpConfig) -> Path:
    return config.registry_dir / "jobs.json"


def read_registry(config: AbaqusMcpConfig) -> dict[str, Any]:
    path = _registry_file(config)
    if not path.exists():
        return {"jobs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"jobs": []}


def write_registry(config: AbaqusMcpConfig, registry: dict[str, Any]) -> None:
    config.registry_dir.mkdir(parents=True, exist_ok=True)
    path = _registry_file(config)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def record_job(config: AbaqusMcpConfig, record: dict[str, Any]) -> None:
    registry = read_registry(config)
    jobs = registry.setdefault("jobs", [])
    jobs.append(record)
    registry["jobs"] = jobs[-500:]
    write_registry(config, registry)


def find_registry_record(config: AbaqusMcpConfig, job_name: str, workdir: Path | None = None) -> dict[str, Any] | None:
    registry = read_registry(config)
    for record in reversed(registry.get("jobs", [])):
        if record.get("job_name") != job_name:
            continue
        if workdir is not None:
            try:
                if Path(record.get("workdir", "")).resolve() != workdir.resolve():
                    continue
            except OSError:
                continue
        return record
    return None


def _has_cmd_metachar(value: str) -> bool:
    return any(char in value for char in ["\n", "\r", "&", "|", "<", ">", "^", "%", "!"])


def _validate_process_args(args: Iterable[str]) -> list[str]:
    clean_args = [str(arg) for arg in args]
    for arg in clean_args:
        if _has_cmd_metachar(arg):
            raise AbaqusMcpError(f"Unsafe shell metacharacter in command argument: {arg!r}")
    return clean_args


def validate_extra_abaqus_args(args: Iterable[str] | None) -> list[str]:
    if not args:
        return []
    clean_args = _validate_process_args(args)
    for arg in clean_args:
        if not EXTRA_ARG_RE.match(arg):
            raise AbaqusMcpError(
                "Unsupported Abaqus extra argument. Use simple Abaqus options "
                "like 'ask_delete=OFF' or 'scratch=C:/temp'."
            )
    return clean_args


def abaqus_base_command(config: AbaqusMcpConfig) -> list[str]:
    command = config.abaqus_command
    command_path = Path(command)
    suffix = command_path.suffix.lower()
    if suffix in {".bat", ".cmd"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
    return [command]


def build_abaqus_command(config: AbaqusMcpConfig, args: Iterable[str]) -> list[str]:
    clean_args = _validate_process_args(args)
    return abaqus_base_command(config) + clean_args


def process_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra_env:
        for key, value in extra_env.items():
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                raise AbaqusMcpError(f"Invalid environment variable name: {key}")
            env[key] = str(value)
    return env


def run_abaqus_foreground(
    config: AbaqusMcpConfig,
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    command = build_abaqus_command(config, args)
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            env=process_env(extra_env),
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            check=False,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = decode_bytes(exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = decode_bytes(exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")

    return {
        "command": command,
        "cwd": str(cwd),
        "return_code": return_code,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.time() - started, 3),
        "stdout": truncate_text(stdout, config.max_capture_bytes),
        "stderr": truncate_text(stderr, config.max_capture_bytes),
    }


def submit_inp_job(
    config: AbaqusMcpConfig,
    *,
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
    inp = ensure_allowed_path(
        inp_path,
        config,
        must_exist=True,
        allowed_extensions={".inp"},
        require_file=True,
    )
    resolved_workdir = (
        ensure_allowed_path(workdir, config, must_exist=True, require_dir=True)
        if workdir
        else inp.parent
    )
    if not resolved_workdir.exists():
        raise AbaqusMcpError(f"Workdir does not exist: {resolved_workdir}")

    name = validate_job_name(job_name or inp.stem)
    if cpus is not None and cpus < 1:
        raise AbaqusMcpError("cpus must be >= 1")
    if gpus is not None and gpus < 0:
        raise AbaqusMcpError("gpus must be >= 0")

    args = [f"job={name}", f"input={inp}"]
    if cpus is not None:
        args.append(f"cpus={cpus}")
    if memory:
        args.append(f"memory={memory}")
    if gpus is not None:
        args.append(f"gpus={gpus}")
    if double_precision:
        args.append("double")
    if wait:
        args.append("interactive")
    args.extend(validate_extra_abaqus_args(extra_args))

    job_paths = AbaqusPaths(job_name=name, workdir=resolved_workdir)

    if wait:
        result = run_abaqus_foreground(
            config,
            args,
            cwd=resolved_workdir,
            timeout_seconds=timeout_seconds,
        )
        result["job_name"] = name
        result["status"] = get_job_status(config, job_name=name, workdir=str(resolved_workdir))
        return result

    command = build_abaqus_command(config, args)
    log_dir = config.registry_dir / "process_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{name}.{int(time.time())}.stdout.log"
    stderr_path = log_dir / f"{name}.{int(time.time())}.stderr.log"

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(resolved_workdir),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=process_env(),
            creationflags=creationflags,
        )

    record = {
        "job_name": name,
        "input_file": str(inp),
        "workdir": str(resolved_workdir),
        "pid": process.pid,
        "submitted_at": now_iso(),
        "command": command,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    record_job(config, record)

    return {
        "job_name": name,
        "pid": process.pid,
        "submitted_at": record["submitted_at"],
        "workdir": str(resolved_workdir),
        "input_file": str(inp),
        "command": command,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "expected_files": {
            ext.lstrip("."): str(job_paths.for_extension(ext))
            for ext in [".log", ".sta", ".msg", ".dat", ".odb", ".lck"]
        },
        "status": get_job_status(config, job_name=name, workdir=str(resolved_workdir)),
    }


def _pid_exists(pid: int | None) -> bool | None:
    if not pid:
        return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_status_from_files(paths: AbaqusPaths) -> dict[str, Any]:
    status = "unknown"
    reasons: list[str] = []
    progress: dict[str, Any] | None = None

    lck = paths.for_extension(".lck")
    log = paths.for_extension(".log")
    sta = paths.for_extension(".sta")
    msg = paths.for_extension(".msg")
    odb = paths.for_extension(".odb")

    if lck.exists():
        status = "running"
        reasons.append(".lck file exists")

    combined_tail_parts = []
    for file_path in (log, sta, msg):
        if file_path.exists() and file_path.is_file():
            combined_tail_parts.append(tail_text_file(file_path, max_bytes=50_000))
    combined_tail = "\n".join(combined_tail_parts)
    combined_upper = combined_tail.upper()

    if sta.exists():
        sta_text = tail_text_file(sta, max_bytes=80_000)
        matches = list(STA_PROGRESS_RE.finditer(sta_text))
        if matches:
            last = matches[-1]
            progress = {
                "step": int(last.group("step")),
                "increment": int(last.group("inc")),
                "total_time": float(last.group("total_time")),
                "step_time": float(last.group("step_time")),
            }
        if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta_text.upper():
            status = "completed"
            reasons.append("status file reports successful completion")

    if "ABAQUS JOB " in combined_upper and " COMPLETED" in combined_upper:
        status = "completed"
        reasons.append("log reports completed")

    error_markers = [
        "ABAQUS ERROR",
        "EXITED WITH AN ERROR",
        "JOB_ABORTED",
        "<ERROR>",
        "HAS NOT BEEN COMPLETED",
        "TOO MANY ATTEMPTS",
    ]
    if any(marker in combined_upper for marker in error_markers):
        if status != "running":
            status = "failed"
        reasons.append("error marker found in Abaqus text output")

    if status == "unknown" and odb.exists():
        status = "odb_present"
        reasons.append("ODB exists but no final status marker was found")

    return {"status": status, "reasons": reasons, "progress": progress}


def get_job_status(
    config: AbaqusMcpConfig,
    *,
    job_name: str,
    workdir: str | None = None,
    include_tail: bool = True,
) -> dict[str, Any]:
    name = validate_job_name(job_name)
    resolved_workdir = (
        ensure_allowed_path(workdir, config, must_exist=True, require_dir=True)
        if workdir
        else None
    )
    record = find_registry_record(config, name, resolved_workdir)
    if resolved_workdir is None:
        if record and record.get("workdir"):
            resolved_workdir = ensure_allowed_path(record["workdir"], config, must_exist=True, require_dir=True)
        else:
            resolved_workdir = config.workspace

    paths = AbaqusPaths(job_name=name, workdir=resolved_workdir)
    parsed = parse_status_from_files(paths)
    pid = int(record["pid"]) if record and record.get("pid") else None
    pid_running = _pid_exists(pid)

    files = {}
    for ext in [".com", ".dat", ".inp", ".ipm", ".log", ".msg", ".odb", ".prt", ".sim", ".sta", ".lck"]:
        path = paths.for_extension(ext)
        files[ext.lstrip(".")] = {
            "path": str(path),
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() and path.is_file() else None,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            if path.exists()
            else None,
        }

    result: dict[str, Any] = {
        "job_name": name,
        "workdir": str(resolved_workdir),
        "status": parsed["status"],
        "reasons": parsed["reasons"],
        "progress": parsed["progress"],
        "pid": pid,
        "pid_running": pid_running,
        "files": files,
    }
    if record:
        result["submitted_at"] = record.get("submitted_at")
        result["command"] = record.get("command")

    if include_tail:
        tails = {}
        for ext in [".log", ".sta", ".msg"]:
            path = paths.for_extension(ext)
            if path.exists() and path.is_file():
                tails[ext.lstrip(".")] = tail_text_file(path, max_bytes=40_000, tail_lines=80)
        result["tail"] = tails

    return result


def list_abaqus_files(
    config: AbaqusMcpConfig,
    *,
    directory: str | None = None,
    recursive: bool = False,
    extensions: list[str] | None = None,
    max_files: int = 200,
) -> dict[str, Any]:
    root = ensure_allowed_path(directory or str(config.workspace), config, must_exist=True, require_dir=True)
    if max_files < 1 or max_files > 5000:
        raise AbaqusMcpError("max_files must be between 1 and 5000")

    wanted = {ext.lower() if ext.startswith(".") else "." + ext.lower() for ext in extensions} if extensions else ABAQUS_EXTENSIONS
    iterator = root.rglob("*") if recursive else root.glob("*")

    files = []
    for path in iterator:
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in wanted:
            continue
        stat = path.stat()
        files.append(
            {
                "path": str(path.resolve()),
                "name": path.name,
                "extension": path.suffix.lower(),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    files.sort(key=lambda item: item["modified"], reverse=True)
    return {"directory": str(root), "recursive": recursive, "count": len(files), "files": files}


def read_abaqus_text_file(
    config: AbaqusMcpConfig,
    *,
    path: str,
    max_bytes: int = 120_000,
    tail_lines: int | None = None,
) -> dict[str, Any]:
    resolved = ensure_allowed_path(
        path,
        config,
        must_exist=True,
        allowed_extensions=TEXT_EXTENSIONS,
        require_file=True,
    )
    if max_bytes < 1 or max_bytes > 2_000_000:
        raise AbaqusMcpError("max_bytes must be between 1 and 2000000")
    text = tail_text_file(resolved, max_bytes=max_bytes, tail_lines=tail_lines)
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "content": text,
    }


def run_abaqus_script(
    config: AbaqusMcpConfig,
    *,
    script_path: str,
    mode: str = "cae",
    workdir: str | None = None,
    script_args: list[str] | None = None,
    timeout_seconds: int = 3600,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    script = ensure_allowed_path(
        script_path,
        config,
        must_exist=True,
        allowed_extensions={".py"},
        require_file=True,
    )
    cwd = ensure_allowed_path(workdir, config, must_exist=True, require_dir=True) if workdir else script.parent
    script_args = script_args or []
    _validate_process_args(script_args)

    if mode == "cae":
        args = ["cae", "noGUI=" + str(script)]
        if script_args:
            args.extend(["--"] + script_args)
    elif mode == "python":
        args = ["python", str(script)] + script_args
    else:
        raise AbaqusMcpError("mode must be 'cae' or 'python'")

    result = run_abaqus_foreground(
        config,
        args,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        extra_env=extra_env,
    )
    result["script_path"] = str(script)
    result["mode"] = mode
    return result


def extract_odb_summary(
    config: AbaqusMcpConfig,
    *,
    odb_path: str,
    step_name: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    odb = ensure_allowed_path(
        odb_path,
        config,
        must_exist=True,
        allowed_extensions={".odb"},
        require_file=True,
    )
    helper = Path(__file__).with_name("odb_extract.py").resolve()
    output_dir = config.registry_dir / "odb_summaries"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / f"{odb.stem}.{int(time.time())}.json"

    args = ["python", str(helper), str(odb), str(output_json)]
    if step_name:
        args.append(step_name)

    run = run_abaqus_foreground(
        config,
        args,
        cwd=odb.parent,
        timeout_seconds=timeout_seconds,
    )
    result: dict[str, Any] = {
        "odb_path": str(odb),
        "output_json": str(output_json),
        "runner": run,
    }
    if output_json.exists():
        result["summary"] = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        result["summary"] = None
    return result


def terminate_job(
    config: AbaqusMcpConfig,
    *,
    job_name: str,
    workdir: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    name = validate_job_name(job_name)
    cwd = ensure_allowed_path(workdir, config, must_exist=True, require_dir=True) if workdir else config.workspace
    result = run_abaqus_foreground(
        config,
        ["terminate", f"job={name}"],
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )
    result["job_name"] = name
    result["status_after_terminate"] = get_job_status(config, job_name=name, workdir=str(cwd))
    return result


def abaqus_environment(config: AbaqusMcpConfig, *, probe: bool = True) -> dict[str, Any]:
    command = config.abaqus_command
    command_path = shutil.which(command) or command
    exists = bool(shutil.which(command)) or Path(command).exists()
    result: dict[str, Any] = {
        "workspace": str(config.workspace),
        "allowed_roots": [str(path) for path in config.allowed_roots],
        "registry_dir": str(config.registry_dir),
        "abaqus_command": command,
        "resolved_abaqus_command": command_path,
        "abaqus_command_exists": exists,
        "python": sys.executable,
        "python_version": sys.version,
    }
    if probe and exists:
        try:
            result["probe"] = run_abaqus_foreground(
                config,
                ["information=release"],
                cwd=config.workspace,
                timeout_seconds=30,
            )
        except Exception as exc:  # noqa: BLE001 - this is diagnostic output for the tool caller.
            result["probe_error"] = str(exc)
    return result
