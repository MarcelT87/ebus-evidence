# ebusd setups

`ebus-evidence` has one deliberately simple compatibility boundary:

```text
eBUS hardware
    ↓
ebusd
    ↓
message-mode raw log
    ↓
ebus-evidence
```

**How ebusd is connected to the eBUS hardware is outside the scope of this project.**

If your existing ebusd installation works and can write a message-mode raw log, you normally do not need to change its adapter configuration for `ebus-evidence`.

---

## Supported data sources

| Data source | Status |
|---|---|
| ebusd in Docker with a readable message-mode raw log | **Supported** |
| ebusd on native/systemd Linux with a readable message-mode raw log | **Supported** |
| Existing ebusd message-mode raw-log file | **Supported** |
| ebusd on another host, with the raw log copied or mounted read-only | **Supported for file-based/offline use** |
| Direct eBUS adapter access | **Intentionally not supported** |
| ebusd byte-mode raw log | **Not supported** |

There are no separate adapter-specific parsers in `ebus-evidence`.

---

## Docker ebusd

For Docker, the important part is that the raw log is available on the Docker host.

Example Compose fragment:

```yaml
services:
  ebusd:
    environment:
      EBUSD_LOGRAWDATA: ""
      EBUSD_LOGRAWDATAFILE: "/rawlog/ebusd.raw"
      EBUSD_LOGRAWDATASIZE: "102400"
    volumes:
      - /srv/ebusd/rawlog:/rawlog
```

This example maps:

```text
container: /rawlog/ebusd.raw
host:      /srv/ebusd/rawlog/ebusd.raw
```

The host path is only an example. Use a path appropriate for your installation.

Check:

```bash
ls -lh /srv/ebusd/rawlog/
head -n 5 /srv/ebusd/rawlog/ebusd.raw
```

Then try automatic discovery:

```bash
ebus-evidence doctor
```

If automatic discovery does not fit the installation, use the host path directly:

```bash
ebus-evidence doctor \
  --raw /srv/ebusd/rawlog/ebusd.raw \
  --profile hw5103-open-evidence
```

### Why the host mount matters

A raw log that exists only inside a disposable container can disappear when that container is replaced.

A host-mounted directory keeps the log independently of the container lifecycle and lets `ebus-evidence` read it directly.

---

## Native/systemd ebusd

For a native Linux installation, the important part is a readable local message-mode raw log.

Typical ebusd raw-log options are:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Do not use byte mode:

```text
--lograwdata=bytes
```

After restarting your existing ebusd service, check:

```bash
ls -lh /var/log/ebusd.raw*
head -n 5 /var/log/ebusd.raw
```

Then:

```bash
ebus-evidence doctor
```

or explicitly:

```bash
ebus-evidence doctor \
  --raw /var/log/ebusd.raw \
  --profile hw5103-open-evidence
```

Where ebusd startup options are configured depends on how ebusd was installed. Do not replace an existing service configuration blindly; add only the required raw-log options to the existing setup.

---

## ebusd on another computer

The current simple approaches are:

1. copy the message-mode raw log to the analysis computer; or
2. make the raw-log directory available through a secure read-only filesystem mount.

Then use the file explicitly:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Remote streaming is not required for the current evidence workflow.

---

## Message mode is required

The supported common input is:

```text
ebusd message-mode raw log
```

A record looks roughly like:

```text
2026-10-01 10:00:00.000 <1008b507020900...
```

Use normal raw logging:

```text
--lograwdata
```

Do not use:

```text
--lograwdata=bytes
```

Byte mode is a different input format and is intentionally outside the current parser scope.

---

## What automatic discovery does

Automatic discovery tries to locate:

- a running ebusd Docker container or native/systemd service;
- the configured raw-log mode;
- the raw-log path;
- for Docker, the host path when the raw directory is mounted.

It does **not** discover, configure or control the eBUS adapter.

If discovery cannot describe an unusual installation, `--raw /path/to/ebusd.raw` remains the simple fallback.

---

## Rule to remember

Do not redesign a working ebusd installation for `ebus-evidence`.

Use:

```text
working ebusd
     ↓
enable or locate message-mode raw log
     ↓
ebus-evidence doctor
     ↓
ebus-evidence analyze
```

That is the intended integration point.

---

## Related documentation

- [Installation and first run](INSTALL.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Community cross-installation test](COMMUNITY_TEST.md)

Upstream ebusd:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
