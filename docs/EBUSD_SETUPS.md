# ebusd setup matrix

This document explains how different **normal ebusd** installations relate to `ebus-evidence`.

The most important rule is:

> `ebus-evidence` does not connect to the eBUS adapter. It reads a normal ebusd **message-mode raw-log file**.

That means the adapter transport and the ebusd installation type are separate questions.

---

## 1. Think in three layers

### Layer A — Where does normal ebusd run?

Examples:

- Docker / Docker Compose;
- native Linux service with systemd;
- manually started Linux process;
- another computer or Raspberry Pi.

This determines **where the raw-log file exists and how ebus-evidence can read it**.

### Layer B — How does ebusd reach the eBUS hardware?

Current ebusd supports several device connection styles, including:

- serial / USB;
- network device by IP;
- UDP network device;
- enhanced protocol with `ens:`;
- enhanced normal-speed mode with `enh:`;
- automatic device discovery through mDNS.

This determines **how ebusd talks to the adapter**.

For normal `ebus-evidence` operation, it does not determine how evidence is parsed.

### Layer C — Is this normal ebusd or micro-ebusd?

Normal ebusd runs as a process/container on a computer.

micro-ebusd is an integrated implementation available on supported ESP32 adapter firmware.

These are different data-source cases.

The current validated `ebus-evidence` input is a raw log produced by **normal ebusd**.

---

# 2. Quick decision table

| Your setup | Can ebus-evidence use it? | Recommended path |
|---|---:|---|
| Docker ebusd + USB adapter | Yes | Docker raw-log mount |
| Docker ebusd + network adapter | Yes | Docker raw-log mount |
| Docker ebusd + `ens:` / `enh:` | Yes | Docker raw-log mount |
| Docker ebusd + mDNS-discovered adapter | Yes | Docker raw-log mount |
| native/systemd ebusd + USB adapter | Yes | local raw-log file |
| native/systemd ebusd + network adapter | Yes | local raw-log file |
| native/systemd ebusd + `ens:` / `enh:` | Yes | local raw-log file |
| native/systemd ebusd + mDNS | Yes | local raw-log file |
| normal ebusd on another computer | Offline: yes | copy or read-only mount the raw log |
| normal ebusd remote live-follow without filesystem access | Not yet | not implemented |
| ebusd client TCP port only | Not as primary input | use the raw-log file |
| micro-ebusd on ESP32 | Not yet validated | wait for dedicated compatibility work |
| ebusd byte-mode raw log | No | enable message-mode raw logging |

---

# 3. Docker ebusd

## 3.1 Docker + USB / serial adapter

Example architecture:

```text
eBUS
  ↓
USB / serial adapter
  ↓
ebusd container
  ↓
message-mode raw log
  ↓
host-mounted raw-log directory
  ↓
ebus-evidence
```

For `ebus-evidence`, the critical part is the mounted raw-log directory.

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

The adapter configuration is intentionally not shown here because it depends on the user's ebusd hardware setup.

After ebusd is running:

```bash
ls -lh /srv/ebusd/rawlog/
head -n 5 /srv/ebusd/rawlog/ebusd.raw
```

Then:

```bash
ebus-evidence doctor
```

If automatic Docker discovery cannot map the file:

```bash
ebus-evidence doctor \
  --raw /srv/ebusd/rawlog/ebusd.raw \
  --profile hw5103-open-evidence
```

---

## 3.2 Docker + network adapter

Example architecture:

```text
eBUS
  ↓
network-capable adapter
  ↓
LAN / Wi-Fi
  ↓
ebusd container
  ↓
message-mode raw log
  ↓
host-mounted raw-log directory
  ↓
ebus-evidence
```

The network connection may use the normal network-device form supported by ebusd or an enhanced device form such as `ens:` / `enh:`.

For `ebus-evidence`, nothing changes:

- do not connect ebus-evidence to the adapter;
- do not expose adapter credentials to ebus-evidence;
- write the normal ebusd message-mode raw log;
- give ebus-evidence read access to that file.

---

## 3.3 Docker + mDNS adapter discovery

If ebusd discovers a compatible adapter through mDNS, the evidence path is still:

```text
adapter
  ↓
normal ebusd
  ↓
message-mode raw log
  ↓
ebus-evidence
```

mDNS changes how ebusd finds the adapter. It does not change the raw-log format expected by `ebus-evidence`.

---

## 3.4 Docker rule of thumb

If this works:

```bash
head -n 5 /path/on/docker-host/ebusd.raw
```

and the lines look like:

```text
2026-10-01 10:00:00.000 <...
```

then the adapter transport is usually no longer relevant to `ebus-evidence`.

---

# 4. Native / systemd ebusd

Example architecture:

```text
eBUS adapter
  ↓
normal ebusd process
  ↓
local message-mode raw log
  ↓
ebus-evidence
```

The adapter can again be:

- serial / USB;
- a network device;
- `ens:`;
- `enh:`;
- mDNS-discovered.

The raw-log requirement remains the same.

Typical raw options:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Do not use:

```text
--lograwdata=bytes
```

After restarting your existing ebusd service:

```bash
ls -lh /var/log/ebusd.raw*
head -n 5 /var/log/ebusd.raw
```

Then try:

```bash
ebus-evidence doctor
```

or explicitly:

```bash
ebus-evidence doctor \
  --raw /var/log/ebusd.raw \
  --profile hw5103-open-evidence
```

### Where are native ebusd options configured?

That depends on how ebusd was installed.

For Debian-based installations, ebusd upstream documents `/etc/default/ebusd` as a common location for daemon options.

Do not replace a working service configuration blindly. Add only the raw-log options appropriate to the existing installation.

---

# 5. ebusd on another computer

There are two supported practical approaches today.

## 5.1 Copy the raw log

Example:

```text
remote ebusd host
  ↓
copy ebusd.raw
  ↓
analysis computer
  ↓
ebus-evidence --raw copied-ebusd.raw
```

Then:

```bash
ebus-evidence analyze \
  --raw /path/to/copied-ebusd.raw \
  --profile hw5103-open-evidence
```

This is the simplest cross-installation method.

## 5.2 Read-only filesystem mount

If the remote raw-log directory is already available through a secure read-only filesystem mount, point `--raw` to that mounted file.

Example architecture:

```text
remote ebusd host
  ↓
read-only filesystem mount
  ↓
local path
  ↓
ebus-evidence
```

### Not implemented yet

`ebus-evidence` does not currently open a remote ebusd client connection and stream the evidence log over TCP.

That is deliberate: the current common evidence format is the message-mode raw-log file.

---

# 6. TCP: two completely different meanings

This distinction causes a lot of confusion.

## 6.1 TCP / network connection to the eBUS adapter

Example:

```text
normal ebusd
  ↓
TCP / enhanced network protocol
  ↓
eBUS adapter
```

This is an **adapter transport**.

It is compatible with the `ebus-evidence` architecture because normal ebusd still produces the raw log.

## 6.2 ebusd client TCP port

Normal ebusd also exposes a client interface used by tools such as `ebusctl`.

The upstream default client port is commonly:

```text
8888
```

Example:

```text
ebusctl
  ↓
TCP port 8888
  ↓
normal ebusd
```

This is not the adapter connection.

`ebus-evidence` does not currently use this client interface as its primary input.

---

# 7. Enhanced device modes: ens and enh

Current ebusd device options include enhanced protocol forms such as:

```text
ens:DEVICE
ens:IP[:PORT]
enh:DEVICE
enh:IP[:PORT]
```

These options describe how normal ebusd communicates with compatible hardware.

They do not require a different `ebus-evidence` parser.

The evidence chain remains:

```text
enhanced adapter
  ↓
normal ebusd
  ↓
message-mode raw log
  ↓
ebus-evidence
```

---

# 8. UDP network devices

Current ebusd also supports network device syntax including a UDP form.

Again, this is between ebusd and the adapter.

If normal ebusd writes the expected message-mode raw log, `ebus-evidence` reads that file exactly like it would for a USB adapter.

---

# 9. mDNS

ebusd can auto-discover compatible device connections through mDNS.

mDNS is not a data source for `ebus-evidence`.

It is only one way normal ebusd may locate its adapter.

No special `ebus-evidence` configuration should be required solely because ebusd used mDNS.

---

# 10. micro-ebusd

micro-ebusd must currently be treated separately.

Current ESP32 adapter firmware can provide integrated micro-ebusd functionality rather than requiring the full normal ebusd daemon on another host.

That changes the data-source boundary:

```text
normal case:
adapter -> normal ebusd -> raw file -> ebus-evidence

micro-ebusd case:
adapter + micro-ebusd -> downloadable/API/log output -> ?
```

The `?` has not yet been validated.

Before declaring micro-ebusd support, this project needs to:

1. obtain a real downloaded/raw micro-ebusd log;
2. document the firmware version;
3. compare its format with normal ebusd message mode;
4. test the existing parser;
5. add a small importer only if required;
6. keep the same normalized frame/evidence model.

Do not feed an unknown micro-ebusd log into the parser and assume that successful parsing proves full compatibility.

---

# 11. Message mode vs byte mode

This project currently expects **message-mode** raw logging.

Use:

```text
--lograwdata
```

with a raw-log filename.

Do not use:

```text
--lograwdata=bytes
```

for the current `ebus-evidence` parser.

Byte mode logs a different level of bus data and is intentionally outside the current supported input format.

---

# 12. Raw-log rotation

Normal ebusd can limit the raw-log size with:

```text
--lograwdatasize=SIZE
```

The active raw log may be rotated to a sibling `.old` file.

For offline analysis:

```bash
ebus-evidence analyze \
  --include-rotated \
  --profile hw5103-open-evidence
```

For persistent live watch, `ebus-evidence` stores a checkpoint and can follow normal rename/create rotation.

If history is no longer available and continuity cannot be proven, watch stops instead of silently claiming a gap-free observation.

---

# 13. What automatic discovery currently means

## Docker

`ebus-evidence doctor` can inspect:

- running Docker container identity;
- ebusd process command line;
- Docker mount metadata.

It uses this to determine:

- whether raw logging is enabled;
- whether it is message mode or byte mode;
- the container raw-log path;
- the corresponding host path when a mount maps it.

It does not need adapter access.

## Native/systemd

Discovery can inspect the running ebusd process/service command line to locate the configured raw log.

If the local installation stores options in a way discovery cannot resolve, use `--raw` manually.

---

# 14. What setup information should be shared?

For cross-installation evidence, useful non-secret context can include:

```text
ebusd installation:
  Docker / native / other

adapter connection:
  USB / serial / network / ens / enh / mDNS / unknown

ebusd version:
configuration source/version:
heating appliance family:
controller:
known device HW/SW versions:
raw-log timestamp timezone if known:
observation duration:
```

Avoid sharing:

- passwords;
- access tokens;
- Wi-Fi credentials;
- public/private IP addresses unless genuinely necessary;
- hostnames;
- unrelated Home Assistant configuration.

The evidence bundle exporter does not automatically add host networking details.

---

# 15. What should I choose?

If normal ebusd is already working, do **not** redesign the adapter connection for `ebus-evidence`.

Use the existing setup.

The preferred path is:

```text
working normal ebusd
        ↓
enable/find message-mode raw log
        ↓
ebus-evidence doctor
        ↓
ebus-evidence analyze
```

The adapter can remain exactly as it is.

---

# 16. Related guides

For first installation:

- [Installation and first run](INSTALL.md)

For contributing evidence from another installation:

- [Community cross-installation test](COMMUNITY_TEST.md)

Upstream ebusd documentation:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
- https://github.com/john30/ebusd/wiki/5.-Tools

ESP32 adapter / micro-ebusd project:

- https://github.com/john30/ebusd-esp32
