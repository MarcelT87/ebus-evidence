# ebusd setups

`ebus-evidence` deliberately does **not** support eBUS adapters directly.

Its supported boundary is much simpler:

```text
eBUS adapter
    ↓
normal ebusd
    ↓
message-mode raw log
    ↓
ebus-evidence
```

If your adapter already works with normal ebusd, its connection type usually does not matter to `ebus-evidence`.

---

## What ebus-evidence actually supports

| Data source | Status |
|---|---|
| Normal ebusd in Docker with a readable message-mode raw log | **Supported** |
| Normal ebusd on native/systemd Linux with a readable message-mode raw log | **Supported** |
| Existing normal ebusd message-mode raw-log file | **Supported** |
| Normal ebusd on another host, with the raw log copied or mounted read-only | **Supported for offline/file-based use** |
| Direct adapter access | **Intentionally not supported** |
| ebusd byte-mode raw log | **Not supported** |

That is the compatibility model.

---

## Adapter connection type is ebusd's job

Normal ebusd can use different adapter transports, for example:

- serial / USB;
- network connections;
- UDP;
- enhanced modes such as `ens:` and `enh:`;
- mDNS discovery.

Those are **ebusd configuration details**.

`ebus-evidence` does not need a separate implementation for each one.

For example, these all lead to the same evidence input:

```text
USB adapter ───────────────┐
TCP/network adapter ───────┤
UDP adapter ───────────────┤
ens:/enh: adapter ─────────┼─> normal ebusd -> message-mode raw log -> ebus-evidence
mDNS-discovered adapter ───┘
```

So there is no separate "USB parser", "TCP parser", or "mDNS parser" in this project.

---

## Docker ebusd

With Docker, the important part is that the raw-log directory is mounted to the host.

Example:

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

Then the host can see:

```text
/srv/ebusd/rawlog/ebusd.raw
```

and `ebus-evidence` can either discover it automatically or use it explicitly:

```bash
ebus-evidence doctor
```

or:

```bash
ebus-evidence doctor \
  --raw /srv/ebusd/rawlog/ebusd.raw \
  --profile hw5103-open-evidence
```

The adapter may be USB, network-connected, or otherwise supported by ebusd. That does not change the `ebus-evidence` workflow.

---

## Native/systemd ebusd

With a native Linux ebusd installation, the important part is the local message-mode raw-log file.

Typical ebusd options are:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Do not use byte mode:

```text
--lograwdata=bytes
```

Then:

```bash
ebus-evidence doctor
```

or:

```bash
ebus-evidence doctor \
  --raw /var/log/ebusd.raw \
  --profile hw5103-open-evidence
```

Again, the adapter transport itself is handled by ebusd.

---

## ebusd on another computer

If normal ebusd runs elsewhere, the current simple options are:

1. copy the raw log and analyze it locally; or
2. make the raw-log directory available through a read-only filesystem mount.

Example:

```bash
ebus-evidence analyze \
  --raw /path/to/copied-ebusd.raw \
  --profile hw5103-open-evidence
```

Direct remote streaming from the ebusd client interface is not currently needed for the core workflow.

---

## TCP: one important distinction

There are two different things people often call "TCP".

### ebusd talking to an adapter

```text
normal ebusd -> network/TCP-style adapter connection -> eBUS adapter
```

This is an ebusd hardware/transport configuration.

It does not require special support in `ebus-evidence`.

### A client talking to ebusd

```text
ebusctl -> ebusd client port
```

The ebusd client interface is a different connection.

`ebus-evidence` does not currently use it as the primary evidence source because the message-mode raw-log file is the common, reproducible input.

---

## Message mode is the common boundary

The current supported input is:

```text
normal ebusd message-mode raw log
```

Use normal ebusd raw logging:

```text
--lograwdata
```

Do not use:

```text
--lograwdata=bytes
```

A typical message-mode record looks roughly like:

```text
2026-10-01 10:00:00.000 <1008b507020900...
```

---

## What automatic discovery means

Automatic discovery only tries to find the normal ebusd process/container and its raw-log path.

For Docker it can use:

- container/process information;
- Docker mount metadata.

For native/systemd it can use:

- service/process information;
- the running ebusd command line.

It does **not** discover or control the eBUS adapter itself.

If discovery does not fit an unusual installation, use:

```bash
--raw /path/to/ebusd.raw
```

---

## The rule to remember

Do not change a working ebusd adapter setup just for `ebus-evidence`.

The preferred flow is:

```text
working normal ebusd
        ↓
enable or locate message-mode raw log
        ↓
ebus-evidence doctor
        ↓
ebus-evidence analyze
```

If normal ebusd can see the bus and write the expected raw log, `ebus-evidence` generally does not care whether the adapter is connected by USB, network, UDP, `ens:`, `enh:`, or mDNS.

---

## Related documentation

- [Installation and first run](INSTALL.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Community cross-installation test](COMMUNITY_TEST.md)

Upstream ebusd:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
