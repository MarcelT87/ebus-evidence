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
    container_id: str
    container_name: str
    image: str
    command: tuple[str, ...]
    raw_enabled: bool
    raw_mode: str | None
    raw_file_container: str | None
    raw_file_host: str | None
    raw_size_kb: int | None
    mounts: tuple[DockerMount, ...]


class DiscoveryError(RuntimeError):
    pass


Runner = Callable[[list[str]], str]


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout


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
    best: tuple[int, DockerMount] | None = None

    for mount in mounts:
        destination = PurePosixPath(mount.destination)
        try:
            relative = path.relative_to(destination)
        except ValueError:
            continue
        score = len(destination.parts)
        if best is None or score > best[0]:
            best = (score, mount)
            best_relative = relative

    if best is None:
        return None

    return str(Path(best[1].source).joinpath(*best_relative.parts))


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
