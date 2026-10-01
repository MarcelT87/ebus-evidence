# ebus-evidence

`ebus-evidence` is a small, deterministic tool for extracting reproducible evidence from existing ebusd raw logs.

It is designed for cross-installation comparisons during eBUS reverse engineering.

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

The first version intentionally supports offline raw-log analysis only. Live watching, MQTT enrichment, Docker and an installer can be added after the core parser/profile/report path is stable.

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

## Quick start

First check that the raw log and profile can be read:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile profiles/hw5103-open-evidence.yaml
```

Then analyze the log:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile profiles/hw5103-open-evidence.yaml
```

Write the machine-readable report as JSON as well:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile profiles/hw5103-open-evidence.yaml \
  --json evidence.json
```

## Raw logging

`ebus-evidence` expects an **existing ebusd message-mode raw log**. It does not modify the ebusd configuration for you.

If raw logging is not enabled yet, configure it in ebusd first and verify that the file is being written before running this tool.

The parser understands the timestamped `<...` / `>...` message-mode records produced by ebusd and performs eBUS byte unescaping before interpreting request lengths.

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

1. continuous read-only watch mode
2. optional device metadata
3. optional MQTT subscription for correlation context
4. Docker image / Compose example
5. native Linux installer and systemd service
6. compact anonymizable evidence bundles for sharing

The raw-log analyzer remains the common core for all installation types.
