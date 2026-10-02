# ebus-evidence

`ebus-evidence` is a small, read-only companion tool for turning existing **ebusd message-mode raw logs** into reproducible evidence for cross-installation eBUS research.

It is intentionally conservative:

- no direct eBUS adapter access;
- no eBUS writes;
- no active probing just to create evidence;
- no automatic semantic naming;
- no confidence scores;
- no cloud upload.

The common input is a raw-log file already written by normal [ebusd](https://github.com/john30/ebusd).

> **Current research scope:** the tool itself is built around normal ebusd message-mode raw logs, but the **bundled evidence profile and the current real-world validation are focused on Vaillant-family systems**, especially the current HW5103 research installation. Other eBUS manufacturers may still be parseable at the raw-log level, but the bundled `hw5103-open-evidence` profile is not intended to produce meaningful coverage for them yet.

## What it can do

- discover normal ebusd in Docker or as a native systemd service;
- analyze existing message-mode raw logs;
- match frames against small YAML evidence profiles;
- count response/value variants;
- follow new raw-log records passively;
- resume after restarts with a rotation-aware checkpoint;
- keep a compact persistent evidence state;
- capture small context windows around explicit rare triggers;
- create deterministic shareable ZIP bundles;
- verify received bundles without extracting them.

Current development version: `0.1.0.dev0`.

## Start here

Before installing anything, first identify **where ebusd runs**.

| Your setup | Start here |
|---|---|
| Home Assistant OS with an eBUSd App/Add-on | **[Home Assistant](docs/HOME_ASSISTANT.md)** |
| ebusd in Docker on a Linux host | **[Installation and first run](docs/INSTALL.md)** |
| ebusd installed directly on Linux/systemd | **[Installation and first run](docs/INSTALL.md)** |
| ebusd on another computer | **[Installation and first run](docs/INSTALL.md)** |
| Not sure | **[Installation and first run](docs/INSTALL.md)** starts with identification steps |

If you use **Home Assistant Container** on a normal Linux/Docker host, the important question is still where ebusd itself runs. See **[Home Assistant](docs/HOME_ASSISTANT.md)**.

For a detailed explanation of Docker, native/systemd and remote ebusd installations, see:

**[ebusd setup matrix](docs/EBUSD_SETUPS.md)**

If something fails during installation, discovery, raw logging, watch/resume, bundle creation or verification, see:

**[Troubleshooting](docs/TROUBLESHOOTING.md)**

## Which setups are supported?

The compatibility boundary is intentionally simple:

| Data source | Current status |
|---|---|
| Normal ebusd in Docker + readable message-mode raw log | **Supported and real-world validated** |
| Normal ebusd via native/systemd Linux + readable message-mode raw log | **Supported; more independent validation wanted** |
| Existing normal ebusd message-mode raw-log file | **Supported** |
| Normal ebusd on another computer | **Offline/file-based use supported** |
| Home Assistant OS eBUSd App/Add-on | **File-based workflow supported; ebus-evidence itself runs elsewhere for now** |
| Direct adapter access | **Intentionally not supported** |
| ebusd `--lograwdata=bytes` | **Not supported** |

The adapter connection itself is ebusd's job and does **not** require separate support in `ebus-evidence`.

```text
adapter -> normal ebusd -> message-mode raw log -> ebus-evidence
```

See **[ebusd setup matrix](docs/EBUSD_SETUPS.md)** for the distinction between ebusd installation type, adapter transport and raw-log access.

## 5-minute quick start

Requirements:

- Python 3.11+
- Git
- an existing normal ebusd message-mode raw log, or a local Docker/systemd ebusd installation that can be discovered

Install:

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -e .
```

Try automatic read-only discovery:

```bash
ebus-evidence doctor
```

Run an analysis:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence
```

If automatic discovery does not fit your setup, provide the raw log manually:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

See **[docs/INSTALL.md](docs/INSTALL.md)** for the complete beginner guide, including how to enable ebusd raw logging.

## Recommended long-running watch

Once `doctor` and `analyze` work:

```bash
mkdir -p data/contexts

ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

Stop with `Ctrl-C`.

This follows the already existing raw log only. It does not generate eBUS traffic.

## Share evidence

Create a deterministic state/context bundle:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --output evidence.zip
```

Verify it before sharing:

```bash
ebus-evidence verify evidence.zip
```

A valid bundle reports:

```text
Status: VALID
```

For a more conservative export without raw context payloads:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --no-context-raw \
  --output evidence-metadata.zip
```

The exporter deliberately omits local resume checkpoint details, absolute local paths, host metadata and credentials. Small context `.raw` files still contain real eBUS payloads and should be reviewed before public sharing.

## Community cross-installation test

A minimal passive workflow for another installation is documented here:

**[Community cross-installation test](docs/COMMUNITY_TEST.md)**

Cross-installation evidence is the main reason this project exists.

## Profiles

Research questions live in YAML profiles rather than hard-coded semantic rules.

The bundled `hw5103-open-evidence` profile currently contains a deliberately small set of evidence checks. More profiles can be added without changing the parser.

A profile can match:

- source;
- target;
- PB/SB;
- exact request or request prefix;

and may optionally decode a simple value from the normalized request or response.

## Raw-log requirement

`ebus-evidence` expects the normal **message-mode** raw log written by ebusd.

Upstream ebusd exposes:

```text
--lograwdata
--lograwdatafile=FILE
--lograwdatasize=SIZE
```

Do not use this for `ebus-evidence`:

```text
--lograwdata=bytes
```

The full Docker and native examples are in **[docs/INSTALL.md](docs/INSTALL.md)**.

## Safety and privacy

The project is designed around passive evidence.

It does not:

- connect directly to the eBUS adapter;
- call arbitrary active `ebusctl read` commands;
- issue `ebusctl write`;
- inject telegrams;
- modify heating parameters;
- publish MQTT messages;
- upload data automatically.

Generated runtime data such as `data/`, `*.raw`, `*.zip`, databases, environment files and private-note directories are ignored by the repository's `.gitignore` to reduce accidental commits.

## Development

Install the development dependencies:

```bash
python -m pip install -e '.[dev]'
pytest
```

The test suite uses synthetic fixtures and does not require a running heating system.

## Relationship to ebusd

[ebusd](https://github.com/john30/ebusd) is the eBUS daemon maintained by John30 and contributors.

`ebus-evidence` is an **independent community project**. It is not part of ebusd and is not presented as an official ebusd component or as being endorsed by the ebusd maintainers.

This repository does not bundle or redistribute ebusd.

Useful upstream references:

- [ebusd repository](https://github.com/john30/ebusd)
- [ebusd wiki](https://github.com/john30/ebusd/wiki)
- [ebusd run options](https://github.com/john30/ebusd/wiki/2.-Run)
- [ebusd Docker Compose example](https://github.com/john30/ebusd/blob/master/contrib/docker/docker-compose.example.yaml)

## License

`ebus-evidence` is released under the MIT License. See [LICENSE](LICENSE).

ebusd is separate software with its own GPL-3.0 license.
