from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


@dataclass(frozen=True, slots=True)
class DockerMount:
    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class EbusdDiscovery:
    installation: str
    command: tuple[str, ...]
    raw_enabled: bool
    raw_mode: str | None
    raw_file_host: str | None
    raw_size_kb: int | None
    container_id: str | None = None
    container_name: str | None = None
    image: str | None = None
    raw_file_container: str | None = None
    mounts: tuple[DockerMount, ...] = ()
    service_name: str | None = None
    pid: int | None = None


class DiscoveryError(RuntimeError):
    pass


Runner = Callable[[list[str]], str]
ProcReader = Callable[[int], list[str]]


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout


def _read_proc_cmdline(pid: int) -> list[str]:
    data = Path(f"/proc/{pid}/cmdline").read_bytes()
    return [part.decode("utf-8", "replace") for part in data.split(b"\0") if part]


def _parse_option(args: list[str], name: str) -> str | None:
    prefix = name + "="
    for index, arg in enumerate(args):
        if arg.startswith(prefix):
            return arg[len(prefix) :]
        if arg == name and index + 1 < len(args) and not args[index + 1].startswith("-"):
            return args[index + 1]
    return None


def parse_ebusd_command(command: list[str]) -> dict[str, object]:
    raw_enabled = False
    raw_mode: str | None = None

    for arg in command:
        if arg == "--lograwdata":
            raw_enabled = True
            raw_mode = "messages"
        elif arg.startswith("--lograwdata="):
            raw_enabled = True
            value = arg.split("=", 1)[1]
            raw_mode = "bytes" if value == "bytes" else "messages"

    raw_file = _parse_option(command, "--lograwdatafile")
    raw_size_text = _parse_option(command, "--lograwdatasize")
    raw_size_kb: int | None = None
    if raw_size_text:
        try:
            raw_size_kb = int(raw_size_text)
        except ValueError:
            raw_size_kb = None

    return {
        "raw_enabled": raw_enabled,
        "raw_mode": raw_mode,
        "raw_file": raw_file,
        "raw_size_kb": raw_size_kb,
    }


def parse_docker_mounts(output: str) -> list[DockerMount]:
    mounts: list[DockerMount] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        source, destination = (part.strip() for part in line.split("|", 1))
        if source and destination:
            mounts.append(DockerMount(source=source, destination=destination))
    return mounts


def map_container_path_to_host(
    container_path: str,
    mounts: list[DockerMount] | tuple[DockerMount, ...],
) -> str | None:
    path = PurePosixPath(container_path)
    best: tuple[int, DockerMount, PurePosixPath] | None = None

    for mount in mounts:
        destination = PurePosixPath(mount.destination)
        try:
            relative = path.relative_to(destination)
        except ValueError:
            continue
        score = len(destination.parts)
        if best is None or score > best[0]:
            best = (score, mount, relative)

    if best is None:
        return None

    return str(Path(best[1].source).joinpath(*best[2].parts))


def _find_ebusd_command(top_output: str) -> list[str] | None:
    for line in top_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split(None, 1)
        args_text = fields[1] if len(fields) == 2 and fields[0].isdigit() else stripped
        try:
            args = shlex.split(args_text)
        except ValueError:
            args = args_text.split()
        if any(PurePosixPath(arg).name == "ebusd" for arg in args):
            return args
    return None


def diagnose_docker_access(runner: Runner = _run_command) -> str | None:
    """Return a concise diagnostic when Docker cannot be inspected.

    This is intentionally read-only: it only runs docker ps and never changes
    Docker or ebusd state. A None result means Docker access itself did not
    explain why ebusd discovery failed.
    """
    if shutil.which("docker") is None and runner is _run_command:
        return None

    try:
        runner(["docker", "ps", "--format", "{{.ID}}"])
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or "").strip()
        stdout = str(exc.stdout or "").strip()
        detail = stderr or stdout
        if "permission denied" in detail.lower():
            return (
                "permission denied while running 'docker ps'; "
                "the current user cannot access the Docker daemon"
            )
        if detail:
            return f"'docker ps' failed: {detail}"
        return "'docker ps' failed"
    except PermissionError:
        return "permission denied while running Docker"
    except (OSError, subprocess.SubprocessError):
        return None

    return None

def discover_docker_ebusd(runner: Runner = _run_command) -> EbusdDiscovery | None:
    if shutil.which("docker") is None and runner is _run_command:
        return None

    try:
        listing = runner(["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"])
    except (OSError, subprocess.SubprocessError):
        return None

    candidates: list[tuple[str, str, str]] = []
    for line in listing.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        container_id, name, image = fields
        text = f"{name} {image}".lower()
        if "ebusd" in text:
            candidates.append((container_id, name, image))

    for container_id, name, image in candidates:
        try:
            top_output = runner(["docker", "top", container_id, "-eo", "pid,args"])
            command = _find_ebusd_command(top_output)
            if not command:
                continue
            mount_output = runner(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{range .Mounts}}{{println .Source "|" .Destination}}{{end}}',
                    container_id,
                ]
            )
        except (OSError, subprocess.SubprocessError):
            continue

        mounts = parse_docker_mounts(mount_output)
        parsed = parse_ebusd_command(command)
        raw_file_container = parsed["raw_file"]
        raw_file_host = (
            map_container_path_to_host(str(raw_file_container), mounts)
            if raw_file_container
            else None
        )

        return EbusdDiscovery(
            installation="docker",
            container_id=container_id,
            container_name=name,
            image=image,
            command=tuple(command),
            raw_enabled=bool(parsed["raw_enabled"]),
            raw_mode=parsed["raw_mode"] if isinstance(parsed["raw_mode"], str) else None,
            raw_file_container=(
                str(raw_file_container) if raw_file_container is not None else None
            ),
            raw_file_host=raw_file_host,
            raw_size_kb=(
                parsed["raw_size_kb"] if isinstance(parsed["raw_size_kb"], int) else None
            ),
            mounts=tuple(mounts),
        )

    return None


def discover_native_ebusd(
    runner: Runner = _run_command,
    proc_reader: ProcReader = _read_proc_cmdline,
) -> EbusdDiscovery | None:
    """Discover a running native systemd ebusd service without reading its environment."""
    if shutil.which("systemctl") is None and runner is _run_command:
        return None

    try:
        state = runner(
            ["systemctl", "show", "ebusd.service", "--property=ActiveState", "--value"]
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None

    if state != "active":
        return None

    try:
        pid_text = runner(
            ["systemctl", "show", "ebusd.service", "--property=MainPID", "--value"]
        ).strip()
        pid = int(pid_text)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None

    if pid <= 0:
        return None

    try:
        command = proc_reader(pid)
    except OSError:
        return None

    if not command or PurePosixPath(command[0]).name != "ebusd":
        return None

    parsed = parse_ebusd_command(command)
    raw_file = parsed["raw_file"]

    return EbusdDiscovery(
        installation="systemd",
        service_name="ebusd.service",
        pid=pid,
        command=tuple(command),
        raw_enabled=bool(parsed["raw_enabled"]),
        raw_mode=parsed["raw_mode"] if isinstance(parsed["raw_mode"], str) else None,
        raw_file_host=str(raw_file) if raw_file is not None else None,
        raw_size_kb=(
            parsed["raw_size_kb"] if isinstance(parsed["raw_size_kb"], int) else None
        ),
    )


def discover_ebusd() -> EbusdDiscovery | None:
    """Discover supported ebusd installations in preferred order."""
    return discover_docker_ebusd() or discover_native_ebusd()
