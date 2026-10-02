# ebus-evidence

`ebus-evidence` turns existing **ebusd message-mode raw logs** into small, reproducible evidence for cross-installation eBUS research.

It is deliberately passive:

- no direct eBUS adapter access;
- no eBUS writes or telegram injection;
- no active probing just to create evidence;
- no MQTT publishing;
- no cloud upload;
- no automatic semantic naming or confidence scores.

The normal data path is:

```text
eBUS adapter -> normal ebusd -> message-mode raw log -> ebus-evidence
```

> **Current research scope:** the parser works on normal ebusd message-mode raw logs. The bundled `hw5103-open-evidence` profile and current real-world validation are focused on **Vaillant-family systems**, especially HW5103/HMU/VWZIO research paths.

## Quick start

Requirements: Linux, Python 3.11+, Git, and a readable normal ebusd message-mode raw log.

```bash
cd ~
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

ebus-evidence doctor
ebus-evidence analyze --profile hw5103-open-evidence
```

If `doctor` cannot auto-discover your setup, use an explicit file:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Do **not** use ebusd byte-mode logging (`--lograwdata=bytes`). The supported common input is normal message-mode raw logging.

## Persistent passive collection

```bash
mkdir -p data/contexts

ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

Stop with `Ctrl-C`. With a saved checkpoint, later runs resume from the previous raw-log position and may replay backlog written while watch was stopped.

Local runtime/evidence files belong under `data/`, which is ignored by Git.

## Create and verify evidence

If you already have an existing `ebusctl scan result`, you can create a privacy-minimized system identity first. See [System identity](docs/SYSTEM_IDENTITY.md). Do not start a new active scan merely for this project.

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --system data/system.json \
  --output data/evidence.zip

ebus-evidence verify data/evidence.zip
```

If no `data/system.json` exists, omit the `--system` line.

Raw context payloads are **excluded by default**. Shared evidence does retain absolute observation/evidence timestamps because timing is part of reproducible evidence; the bundle and verifier disclose this explicitly.

## Supported setups

| Setup | Current status |
|---|---|
| normal ebusd in Docker + readable message-mode raw log | supported and real-world validated |
| normal ebusd via native/systemd + readable message-mode raw log | supported; more independent validation wanted |
| copied/read-only mounted message-mode raw log | supported |
| Home Assistant OS eBUSd App/Add-on | file-based workflow |
| direct adapter access | intentionally unsupported |
| ebusd byte-mode raw log | unsupported |

The adapter transport used by ebusd is outside the evidence boundary.

## Documentation

- **[Installation and first run](docs/INSTALL.md)** — complete beginner path
- **[Home Assistant](docs/HOME_ASSISTANT.md)** — Home Assistant-specific route
- **[ebusd setup matrix](docs/EBUSD_SETUPS.md)** — Docker/native/remote layouts
- **[System identity](docs/SYSTEM_IDENTITY.md)** — privacy-minimized hardware/firmware identity
- **[Community test](docs/COMMUNITY_TEST.md)** — cross-installation contribution workflow
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** — symptom-based help
- **[Project boundaries](docs/PROJECT_BOUNDARIES.md)** — what this repository owns and what stays outside it

## Development

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

Tests use synthetic fixtures and do not require a heating system.

## Relationship to ebusd

[ebusd](https://github.com/john30/ebusd) is a separate project maintained by John30 and contributors.

`ebus-evidence` is an independent community project. It is not part of ebusd and does not bundle or redistribute ebusd.

## License

MIT. See [LICENSE](LICENSE).
