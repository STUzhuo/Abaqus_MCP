from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ABAQUS_BAT = r"C:\SIMULIA\Commands\abaqus.bat"


def _split_paths(value: str | None) -> list[Path]:
    if not value:
        return []
    return [Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()]


@dataclass(frozen=True)
class AbaqusMcpConfig:
    workspace: Path
    allowed_roots: tuple[Path, ...]
    abaqus_command: str
    registry_dir: Path
    max_capture_bytes: int = 200_000

    @classmethod
    def from_env(cls) -> "AbaqusMcpConfig":
        # Keep configuration in environment variables so the same package can be
        # used from Codex, Claude Desktop, or a plain terminal without editing
        # source files.  The workspace is also the default security boundary.
        workspace = Path(os.environ.get("ABAQUS_MCP_WORKSPACE", os.getcwd())).expanduser().resolve()
        extra_roots = _split_paths(os.environ.get("ABAQUS_MCP_ALLOWED_DIRS"))
        allowed = [workspace]
        allowed.extend(path.resolve() for path in extra_roots)

        # Many Windows Abaqus installs expose only abaqus.bat.  We still prefer
        # PATH lookup first, because Linux and managed clusters usually provide
        # an `abaqus` executable/module wrapper.
        abaqus_command = (
            os.environ.get("ABAQUS_COMMAND")
            or shutil.which("abaqus")
            or DEFAULT_ABAQUS_BAT
        )
        registry_dir = Path(os.environ.get("ABAQUS_MCP_REGISTRY_DIR", workspace / ".abaqus_mcp")).expanduser()
        if not registry_dir.is_absolute():
            registry_dir = workspace / registry_dir

        max_capture = int(os.environ.get("ABAQUS_MCP_MAX_CAPTURE_BYTES", "200000"))

        return cls(
            workspace=workspace,
            allowed_roots=tuple(dict.fromkeys(path.resolve() for path in allowed)),
            abaqus_command=abaqus_command,
            registry_dir=registry_dir.resolve(),
            max_capture_bytes=max_capture,
        )
