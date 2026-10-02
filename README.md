# ebus-evidence

`ebus-evidence` turns existing **ebusd message-mode raw logs** into small,
reproducible evidence for cross-installation eBUS research.

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

> **Current research scope:** the parser works on normal ebusd message-mode raw
> logs. The bundled `hw5103-open-evidence` profile and current real-world
> validation are focused on **Vaillant-family systems**, especially
> HW5103/HMU/VWZIO research paths.

## Beginner workflow

For the normal Linux/Docker or native ebusd path, the intended workflow is:

```text
install -> doctor -> collect -> export
```

Requirements: Linux, Python 3.11+, Git, and a readable normal ebusd
message-mode raw log.

### 1. Install

```bash
cd ~
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence
bash install.sh
```

The installer creates a local `.venv`, installs the checkout and enables the
local `./evidence` launcher. It does not configure or access the eBUS adapter.

### 2. Check

```bash
./evidence doctor
```

If `doctor` cannot auto-discover your setup, use an explicit file:

```bash
./evidence doctor --raw /path/to/ebusd.raw --profile hw5103-open-evidence
```

Do **not** use ebusd byte-mode logging (`--lograwdata=bytes`). The supported
common input is normal message-mode raw logging.

### 3. Collect

```bash
./evidence collect
```

Collection is passive and read-only. There is no normal collection timer; it
keeps following new raw-log records until you stop it with `Ctrl-C`.

The beginner command automatically uses:

```text
profile:   hw5103-open-evidence
state:     data/evidence-state.json
contexts:  data/contexts
```

A later `./evidence collect` resumes from the saved checkpoint when continuity
can be proven. It does not silently discard a gap.

Check progress at any time with:

```bash
./evidence status
```

### Existing/static raw-log file

If you already have a **static copy** of an ebusd message-mode raw log, do not
use live collection just to replay history. Import the existing file from
beginning to end:

```bash
./evidence doctor --raw /path/to/ebusd.raw --profile hw5103-open-evidence
./evidence import --raw /path/to/ebusd.raw
./evidence export
```

`import` is read-only, does not require ebusd to be running locally and refuses
to mix the imported history with an existing evidence state.

### 4. Export a verified ZIP

```bash
./evidence export
```

This creates:

```text
data/evidence.zip
```

and immediately verifies the bundle.

If `data/system.json` exists and is valid, it is included automatically.
Raw context payloads remain **excluded by default**.

The successful result ends with:

```text
Status .............. VALID
Deterministic ....... yes
Ready to share.
```

## Optional system identity

For cross-installation hardware/firmware comparison, an existing
`ebusctl scan result` can be converted into a privacy-minimized
`data/system.json`.

No scan is initiated by `ebus-evidence`.

See **[System identity](docs/SYSTEM_IDENTITY.md)**.

## Advanced / explicit commands

The beginner commands are convenience wrappers around the same implementation.
The explicit expert interface remains available:

```text
ebus-evidence doctor
ebus-evidence import
ebus-evidence analyze
ebus-evidence watch
ebus-evidence system
ebus-evidence bundle
ebus-evidence verify
```

Use the explicit commands when you need custom profiles, paths, timezone
handling, JSON analysis output, checkpoint controls or explicit bundle options.

For example:

```bash
source .venv/bin/activate

ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

`analyze` inspects existing raw-log history. It does **not** create the
persistent evidence state used by `collect` or `import` before export.

## Privacy

The normal export:

- excludes raw context payloads;
- excludes absolute host paths;
- excludes resume checkpoint/device/inode details;
- excludes host metadata and credentials;
- retains absolute observation/evidence timestamps because timing is part of
  reproducible evidence;
- explicitly discloses timestamp retention in the bundle/verifier output.

Only use `--include-context-raw` when you deliberately want reviewed raw
context payloads in the ZIP.

## Supported setups

| Setup | Current status |
|---|---|
| normal ebusd in Docker + readable message-mode raw log | supported and real-world validated |
| normal ebusd via native/systemd + readable message-mode raw log | supported; more independent validation wanted |
| copied/static message-mode raw log | supported through `import` |
| read-only mounted growing message-mode raw log | supported through `collect` |
| Home Assistant OS eBUSd App/Add-on | file-based workflow |
| direct adapter access | intentionally unsupported |
| ebusd byte-mode raw log | unsupported |

The adapter transport used by ebusd is outside the evidence boundary.

## Documentation

- **[Installation and first run](docs/INSTALL.md)** — beginner and advanced paths
- **[ebusd setup matrix](docs/EBUSD_SETUPS.md)** — Docker/native/remote layouts
- **[System identity](docs/SYSTEM_IDENTITY.md)** — privacy-minimized hardware/firmware identity
- **[Community test](docs/COMMUNITY_TEST.md)** — cross-installation contribution workflow
- **[Home Assistant](docs/HOME_ASSISTANT.md)** — special file-based route for Home Assistant users
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

[ebusd](https://github.com/john30/ebusd) is a separate project maintained by
John30 and contributors.

`ebus-evidence` is an independent community project. It is not part of ebusd
and does not bundle or redistribute ebusd.

## License

MIT. See [LICENSE](LICENSE).
