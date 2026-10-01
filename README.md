# ebus-evidence

`ebus-evidence` is a small, deterministic companion tool for extracting reproducible evidence from raw logs produced by [ebusd](https://github.com/john30/ebusd).

It is designed for cross-installation comparisons during eBUS reverse engineering. The current development line intentionally focuses on **ebusd as the supported data source**.

## What it does

- reads an existing ebusd message-mode raw log
- matches frames against small YAML profiles
- counts requests, responses and value variants
- can decode simple numeric fields
- exports a human-readable summary and optional JSON

It does **not** guess semantic names.

It does **not** connect to the eBUS adapter, send eBUS commands, write parameters or publish MQTT messages.

## Status

Early development preview (`0.1.0.dev0`).

The first versions intentionally target **ebusd message-mode raw logs only**. This keeps installation, diagnostics and evidence collection predictable while the core is still being developed.

Live watching, automatic ebusd discovery, MQTT enrichment, Docker packaging and an installer can be added after the core parser/profile/report path is stable.

## Relationship to ebusd

[ebusd](https://github.com/john30/ebusd) is the eBUS daemon maintained by **John30 and contributors**. It handles the actual communication with eBUS hardware and can create the raw message logs that `ebus-evidence` analyzes.

`ebus-evidence` is an **independent community project**. It is not part of ebusd and is not presented as an official ebusd component or as being endorsed by the ebusd maintainers.

This repository does not bundle or redistribute ebusd. It only reads log files produced by it and documents the ebusd options needed for interoperability.

ebusd is distributed under the **GNU General Public License v3.0**; see the license and documentation in the upstream [john30/ebusd repository](https://github.com/john30/ebusd).

## Requirements

- Linux, macOS or Windows with Python 3.11+
- an existing ebusd message-mode raw log

No Proxmox, Docker, Home Assistant, MQTT or analyzer database is required.

## Installation

Clone the repository and create a Python virtual environment:

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## Getting an ebusd raw log

`ebus-evidence` needs an ebusd **message-mode raw log**. If you do not have ebusd yet, start with the upstream [ebusd project and installation documentation](https://github.com/john30/ebusd).

If you already have a file containing timestamped lines with `<...` or `>...`, you can use it directly.

Example:

```text
2026-10-01 10:00:00.000 <1008b507020900...
```

### Native / systemd ebusd

Add these options wherever your ebusd startup arguments are configured:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Then restart ebusd.

`102400` means about 100 MiB. ebusd rotates the active file to `ebusd.raw.old` when the configured size is reached.

Do **not** use:

```text
--lograwdata=bytes
```

That enables byte-level logging, while `ebus-evidence` currently expects the normal message-mode raw log.

### Docker / Docker Compose

With the official ebusd Docker environment variables, the same setup can look like this:

```yaml
services:
  ebusd:
    environment:
      EBUSD_LOGRAWDATA: ""
      EBUSD_LOGRAWDATAFILE: "/rawlog/ebusd.raw"
      EBUSD_LOGRAWDATASIZE: "102400"
    volumes:
      - ./rawlog:/rawlog
```

Recreate or restart the ebusd container after changing the configuration.

The raw log will then be available on the Docker host in:

```text
./rawlog/ebusd.raw
```

and, after rotation, possibly:

```text
./rawlog/ebusd.raw.old
```

### Check that it works

First check that the file exists and is growing:

```bash
ls -lh /path/to/ebusd.raw*
```

Then inspect the first few records:

```bash
head -n 5 /path/to/ebusd.raw
```

You should see timestamps followed by `<...` or `>...` raw telegram data.

Finally let `ebus-evidence` verify the file:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile profiles/hw5103-open-evidence.yaml
```

If a rotated `.old` file exists, add `--include-rotated`.

### Timestamp timezone

ebusd raw records contain a timestamp without an explicit UTC offset. `ebus-evidence` therefore **does not guess the timezone**.

Without extra options, reports preserve the exact raw timestamp and label its timezone as unspecified.

If you know the timezone used by ebusd, provide it explicitly:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --source-timezone UTC \
  --profile profiles/hw5103-open-evidence.yaml
```

You can additionally choose a timezone for human-readable output:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --source-timezone UTC \
  --display-timezone Europe/Berlin \
  --profile profiles/hw5103-open-evidence.yaml
```

The JSON report keeps the original raw timestamp and, when a source timezone is supplied, also records a normalized UTC timestamp and a display timestamp.

> ebusd installations differ. The important part is not where ebusd runs, but that `ebus-evidence` can read the message-mode raw log file. No Proxmox, Docker, MQTT or analyzer database is required.

## Quick start

On a Linux host running ebusd in Docker **or as a native systemd service**, try automatic read-only discovery first:

```bash
ebus-evidence doctor
```

`doctor` reads only the running ebusd process arguments needed for raw-log detection. For Docker it additionally reads mount metadata so the container raw-log path can be mapped to its host path. For native systemd it reads the service's main PID and that process's command line. It does **not** inspect or print process/container environments, and it does not change ebusd.

If automatic discovery is not available or your setup is unusual, use the manual raw-log path:

First check that the raw log and profile can be read:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile profiles/hw5103-open-evidence.yaml
```

Then analyze the log. When ebusd discovery works, neither the raw-log path nor the repository profile path is needed:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence
```

For an unusual setup, override the raw-log path explicitly:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

If ebusd also has a rotated `ebusd.raw.old`, include it in the same chronological analysis:

```bash
ebus-evidence analyze \
  --include-rotated \
  --profile hw5103-open-evidence
```

Write the machine-readable report as JSON as well:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence \
  --json evidence.json
```

## Live watch

After `doctor` and `analyze` work, `watch` can follow **new** ebusd raw-log records without reprocessing the historical file:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence
```

It starts at the current end of the raw log, prints only matching profile evidence, and follows ebusd rename/create rotation. Stop it with `Ctrl-C`.

For a short diagnostic run:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --seconds 15
```

`watch` does not create a database and does not access the eBUS adapter. It only follows the already configured raw-log file.

## Raw logging

`ebus-evidence` expects an **existing ebusd message-mode raw log**. It does not modify the ebusd configuration for you.

If raw logging is not enabled yet, configure it in ebusd first and verify that the file is being written before running this tool.

The parser understands the timestamped `<...` / `>...` message-mode records produced by ebusd and performs eBUS byte unescaping before interpreting request lengths.

ebusd commonly rotates `FILE` to `FILE.old`. The optional `--include-rotated` flag reads `FILE.old` first and the active `FILE` second, so evidence does not disappear merely because the raw log rotated.

## Profiles

Research questions live in YAML profiles rather than in hard-coded semantic logic.

A check can select a source, target, PB/SB and exact request or request prefix. It may optionally decode a value from the normalized request or response.

Example:

```yaml
- id: b512_states
  description: Observed VWZIO B512 /0613 state values
  match:
    source: "03"
    target: "76"
    pbsb: "b512"
    request_prefix: "0613"
  value:
    from: request
    type: u8
    offset: 6
```

The bundled `hw5103-open-evidence` profile currently contains a few deliberately simple discriminator checks. More profiles can be added without changing the parser.

## Safety model

The current version is offline and filesystem-only:

```text
ebusd raw log -> ebus-evidence -> report
```

There is no adapter access and no active eBUS access.

Future live integrations should preserve the same rule: consume passive evidence, do not generate bus traffic.

## Development

Install the development dependencies and run the tests:

```bash
pip install -e '.[dev]'
pytest
```

The tests use small synthetic raw-log fixtures. They do not require a running ebusd instance.

## Planned next steps

Once the offline core is stable:

1. harden automatic read-only ebusd discovery across real Docker and native/systemd installations
2. harden continuous read-only watch mode and add compact state persistence
3. optional ebusd device metadata
4. optional MQTT subscription for correlation context
5. Docker image / Compose example
6. native Linux installer and systemd service
7. compact anonymizable evidence bundles for sharing

The raw-log analyzer remains the common core for all installation types.


## License

`ebus-evidence` is released under the MIT License. See [LICENSE](LICENSE).

The ebusd project is separate software with its own GPL-3.0 license.
