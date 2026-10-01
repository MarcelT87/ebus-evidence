from ebus_evidence.discovery.ebusd import (
    DockerMount,
    discover_docker_ebusd,
    map_container_path_to_host,
    parse_ebusd_command,
)


def test_parse_ebusd_message_raw_options():
    parsed = parse_ebusd_command(
        [
            "ebusd",
            "--scanconfig",
            "--lograwdata",
            "--lograwdatafile=/ebusd-raw/ebusd.raw",
            "--lograwdatasize=102400",
        ]
    )
    assert parsed["raw_enabled"] is True
    assert parsed["raw_mode"] == "messages"
    assert parsed["raw_file"] == "/ebusd-raw/ebusd.raw"
    assert parsed["raw_size_kb"] == 102400


def test_parse_ebusd_bytes_mode():
    parsed = parse_ebusd_command(["ebusd", "--lograwdata=bytes"])
    assert parsed["raw_enabled"] is True
    assert parsed["raw_mode"] == "bytes"


def test_map_container_raw_path_to_host():
    mounts = [
        DockerMount(
            source="/opt/docker/ebusd/rawlog",
            destination="/ebusd-raw",
        )
    ]
    assert (
        map_container_path_to_host("/ebusd-raw/ebusd.raw", mounts)
        == "/opt/docker/ebusd/rawlog/ebusd.raw"
    )


def test_docker_discovery_uses_process_args_and_mounts_only(monkeypatch):
    monkeypatch.setattr("ebus_evidence.discovery.ebusd.shutil.which", lambda name: "/usr/bin/docker")

    responses = {
        ("docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"):
            "abc123\tebusd\tjohn30/ebusd:latest\n",
        ("docker", "top", "abc123", "-eo", "pid,args"):
            "PID COMMAND\n123 ebusd --scanconfig --lograwdata "
            "--lograwdatafile=/ebusd-raw/ebusd.raw --lograwdatasize=102400\n",
        (
            "docker",
            "inspect",
            "--format",
            '{{range .Mounts}}{{println .Source "|" .Destination}}{{end}}',
            "abc123",
        ):
            "/opt/docker/ebusd/rawlog | /ebusd-raw\n",
    }

    def fake_runner(command):
        return responses[tuple(command)]

    result = discover_docker_ebusd(runner=fake_runner)
    assert result is not None
    assert result.container_name == "ebusd"
    assert result.raw_mode == "messages"
    assert result.raw_file_container == "/ebusd-raw/ebusd.raw"
    assert result.raw_file_host == "/opt/docker/ebusd/rawlog/ebusd.raw"
    assert result.raw_size_kb == 102400
