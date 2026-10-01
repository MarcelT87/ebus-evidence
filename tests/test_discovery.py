from ebus_evidence.discovery.ebusd import (
    DockerMount,
    discover_docker_ebusd,
    discover_native_ebusd,
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


def test_native_systemd_discovery_reads_main_pid_cmdline_only(monkeypatch):
    monkeypatch.setattr(
        "ebus_evidence.discovery.ebusd.shutil.which",
        lambda name: "/usr/bin/systemctl",
    )

    responses = {
        (
            "systemctl",
            "show",
            "ebusd.service",
            "--property=ActiveState",
            "--value",
        ): "active\n",
        (
            "systemctl",
            "show",
            "ebusd.service",
            "--property=MainPID",
            "--value",
        ): "4711\n",
    }

    def fake_runner(command):
        return responses[tuple(command)]

    def fake_proc_reader(pid):
        assert pid == 4711
        return [
            "/usr/bin/ebusd",
            "--scanconfig",
            "--lograwdata",
            "--lograwdatafile=/var/log/ebusd.raw",
            "--lograwdatasize=102400",
        ]

    result = discover_native_ebusd(runner=fake_runner, proc_reader=fake_proc_reader)
    assert result is not None
    assert result.installation == "systemd"
    assert result.service_name == "ebusd.service"
    assert result.pid == 4711
    assert result.raw_mode == "messages"
    assert result.raw_file_host == "/var/log/ebusd.raw"
    assert result.raw_size_kb == 102400


def test_native_systemd_discovery_ignores_inactive_service(monkeypatch):
    monkeypatch.setattr(
        "ebus_evidence.discovery.ebusd.shutil.which",
        lambda name: "/usr/bin/systemctl",
    )

    def fake_runner(command):
        return "inactive\n"

    assert discover_native_ebusd(runner=fake_runner, proc_reader=lambda pid: []) is None
