# Installation and first run

This guide is for users who already have an eBUS installation and want to
collect **passive, reproducible evidence** with `ebus-evidence`.

You do not need Home Assistant, MQTT, Proxmox or an analyzer database.

`ebus-evidence` does not talk to the eBUS adapter and does not send eBUS
commands. It reads a message-mode raw log that is already written by normal
`ebusd`.

The normal beginner workflow is:

```text
install -> doctor -> collect -> export
```

---

## 1. Before installing: where does ebusd run?

Choose the closest option.

### A. Home Assistant OS with an eBUSd App/Add-on

Examples:

- Home Assistant Green;
- Home Assistant Yellow;
- Home Assistant OS on Raspberry Pi;
- Home Assistant OS in a VM.

Do **not** start with `git clone` on the Home Assistant OS host.

Use the dedicated path:

**[Home Assistant](HOME_ASSISTANT.md)**

The current recommended workflow is to let the eBUSd App write the message-mode
raw log, copy that file to a normal computer, then import it into an exportable
evidence state.

### B. ebusd in Docker on a Linux host

Install `ebus-evidence` on the **Linux Docker host**, not inside the ebusd
container.

Continue below.

### C. ebusd installed directly on Linux

Install `ebus-evidence` on that Linux machine.

Continue below.

### D. ebusd runs on another computer

Install `ebus-evidence` on a normal computer. Import a completed/static copied
raw log, or use `collect` against a read-only mounted raw log that continues to
grow.

### E. I do not know where ebusd runs

On a normal Linux machine, try:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}' | grep -i ebusd
systemctl is-active ebusd
```

If neither applies, ebusd may run on another computer or inside Home Assistant
OS. Identify that host before changing anything.

---

## 2. Requirements

The easiest supported environment is Linux with:

- Python 3.11 or newer;
- Git;
- Python virtual-environment support;
- read access to an ebusd message-mode raw log.

Check:

```bash
python3 --version
git --version
```

On Debian/Ubuntu/Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

---

## 3. Install

Use a normal user account and any directory where that user can write.

The project does **not** require a specific installation path and does not need
to live next to ebusd, Docker or under `/opt`. The home directory in the first
example is only a convenient default:

```bash
cd ~   # example only
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence
bash install.sh
```

An explicit destination works as well:

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git /path/to/ebus-evidence
cd /path/to/ebus-evidence
bash install.sh
```

The local `.venv`, launcher and default `data/` runtime files stay relative
to the chosen checkout.

The installer:

- checks for Python 3.11+;
- creates a local `.venv` when needed;
- installs the current checkout;
- enables the local `./evidence` launcher.

It does **not**:

- access the eBUS adapter;
- change ebusd configuration;
- start an eBUS scan;
- publish anything.

Check:

```bash
./evidence --version
./evidence --help
```

You do not need to activate the virtual environment when using `./evidence`.

### Advanced/manual installation

The standard Python path remains supported:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

---

## 4. Check the existing ebusd/raw-log setup

Try:

```bash
./evidence doctor
```

`doctor` is read-only.

It checks whether it can identify normal Docker/native ebusd and locate its
configured raw log.

It does not send bus traffic or modify the heating system.

If the raw log is usable, continue to **Collect evidence** below.

When you run the bare beginner command `./evidence doctor`, the line

```text
Profile .............. not checked
```

is expected. `doctor` is validating discovery/raw-log readiness at that point.
The normal bundled profile is loaded and validated by `./evidence collect`.

If discovery does not fit your installation, use a file explicitly:

```bash
./evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

---

## 5. If message-mode raw logging is not enabled

`ebus-evidence` needs normal ebusd **message-mode** raw logging.

Message mode is an ebusd-generated transaction representation rather than a
lossless physical-wire capture. The parser therefore validates CRCs and
transaction framing before creating Evidence and contains one narrow,
fail-closed compatibility path for the currently known ebusd echo-logging
artefact documented in [ebusd setups](EBUSD_SETUPS.md#message-mode-is-not-a-lossless-wire-capture).
You do not need to change a working ebusd setup for that case.

Do not use:

```text
--lograwdata=bytes
```

### Docker ebusd

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

The example maps:

```text
container: /rawlog/ebusd.raw
host:      /srv/ebusd/rawlog/ebusd.raw
```

Use a path appropriate for your own installation.

After applying your normal Docker configuration/restart procedure:

```bash
ls -lh /srv/ebusd/rawlog/
head -n 5 /srv/ebusd/rawlog/ebusd.raw
```

A host mount matters because a raw log that exists only inside a disposable
container can disappear when the container is recreated.

### Native/systemd ebusd

Typical options are:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Add them to the place where **your existing ebusd startup arguments are
configured**. Do not replace a working service definition blindly.

After restarting using your normal setup:

```bash
ls -lh /var/log/ebusd.raw*
head -n 5 /var/log/ebusd.raw
```

More setup examples are in **[ebusd setups](EBUSD_SETUPS.md)**.

---

## 6. Collect evidence

For the normal supported Vaillant/HW5103 workflow:

```bash
./evidence collect
```

The command automatically uses:

```text
profile:      hw5103-open-evidence
state:        data/evidence-state.json
context-dir:  data/contexts
raw log:      auto-discovered when possible
```

There is **no normal collection timer**. The command keeps following the raw
log until you stop it yourself with:

```text
Ctrl-C
```

Collection is passive. It follows records written by ebusd and does not generate
bus traffic.

The persistent state is required for the normal `collect -> export` workflow.
This is the step that builds the evidence state used by the ZIP.

A later run:

```bash
./evidence collect
```

reuses the saved checkpoint and resumes when continuity can be proven.

If a future update raises the bundled profile version, the first writer run
automatically starts a new **observation epoch**:

- the previous profile/version observation is preserved as historical evidence;
- the raw-log checkpoint is preserved, so old traffic is not replayed;
- the new profile version starts at 0 observed frames;
- checks added by the new profile therefore do not inherit earlier coverage.

`status` and `export` remain read-only. If they see a newer profile before
the first post-update writer run, they preview the rollover in memory.
`export` can already create a valid bundle containing the historical epoch and
a zero-frame active epoch without modifying the local state. A later
`collect`/expert `watch --state` persists that rollover under the normal
single-writer lock.

Historical context files remain local. Context metadata from an older profile
version is not silently relabeled or exported as current-profile context.

Only one state-writing process may use the same evidence state at a time.
`collect`, `import`, and expert `watch --state` share the same local
single-writer lock. If another writer is already using that state, the second
command stops with a clear error instead of risking divergent checkpoints or
overwriting evidence.

The small hidden `.writer.lock` file may remain after the command exits. That
is expected: lock ownership is held by the operating system, not by the
existence of the file. Do not delete the file to try to override a genuinely
running writer.

The optional `--seconds` argument is reserved for controlled diagnostics and
automated tests. Beginners do not need it for normal collection.

With a manual **growing/live** raw-log path:

```bash
./evidence collect --raw /path/to/ebusd.raw
```

### Import an existing static raw-log file

If the file is a completed/copy of existing history rather than a live growing
log, use:

```bash
./evidence import --raw /path/to/ebusd.raw
```

The import:

- reads the source from beginning to end without modifying it;
- uses the same evidence profile and parser as live collection;
- creates the normal `data/evidence-state.json` used by export;
- refuses to mix with an existing evidence state;
- aborts if the source file changes while it is being imported;
- stages state/context output privately and publishes the state last as the
  completion marker;
- rolls context publication back if the final state publication fails, so a
  failed import does not leave a context-only result behind.

If a sibling `FILE.old` belongs to the same copied history:

```bash
./evidence import --raw /path/to/ebusd.raw --include-rotated
```

Then export normally:

```bash
./evidence export
```

---

## 7. Check collection status

At any time:

```bash
./evidence status
```

The status command reports:

- whether the raw log can be resolved;
- active profile;
- whether evidence state exists and is valid;
- observed frame/event counts;
- available context metadata;
- optional system identity;
- whether there is evidence ready to export.

For a manual raw-log setup:

```bash
./evidence status --raw /path/to/ebusd.raw
```

---

## 8. Optional: add system identity

For cross-installation hardware/firmware comparison, add a structured system
identity when an **existing** `ebusctl scan result` is already available.

Do not run `ebusctl scan` or `ebusctl scan full` merely for this project.

Follow **[System identity](SYSTEM_IDENTITY.md)** to create:

```text
data/system.json
```

If no existing scan result is available, skip this step. Export still works.

---

## 9. Export and verify the shareable ZIP

Run:

```bash
./evidence export
```

The command uses the standard local paths automatically:

- `data/evidence-state.json`;
- `data/contexts` when present;
- `data/system.json` when present and valid;
- output `data/evidence.zip`.

It then immediately runs the bundle verifier and the normal public-submission policy.

A successful result reports:

```text
Status .............. VALID
Deterministic ....... yes
Public submission ... PASS

Ready to share.
```

Raw context payloads are excluded by default.

If the ZIP is structurally valid but does not satisfy the normal public
submission policy, export keeps the local ZIP but reports
`Public submission ... NOT READY (...)` instead of `Ready to share.`.
Do not upload that file through the normal Evidence submission form until the
reported policy reason is resolved.

Absolute observation/evidence timestamps remain included because timing is
research evidence. The bundle and verifier disclose this explicitly.

Only if you intentionally want reviewed raw context payloads inside the ZIP:

```bash
./evidence export --include-context-raw
```

Review such raw context before publishing it.

---

## 10. Optional: inspect existing raw-log history

`analyze` is useful for inspecting historical data:

```bash
./evidence analyze --profile hw5103-open-evidence
```

or:

```bash
./evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Important:

> `analyze` does **not** create the persistent evidence state used by either
> `collect -> export` or `import -> export`.

This keeps offline analysis separate from persistent evidence collection.

Optional shareable JSON:

```bash
./evidence analyze \
  --profile hw5103-open-evidence \
  --json data/analysis.json
```

The JSON omits the absolute raw-log host path but retains/discloses absolute
evidence timestamps.

---

## 11. Advanced explicit commands

Experienced users can continue to use the full interface:

```text
ebus-evidence doctor
ebus-evidence import
ebus-evidence analyze
ebus-evidence watch
ebus-evidence system
ebus-evidence bundle
ebus-evidence verify
```

Example explicit persistent watch:

```bash
source .venv/bin/activate

ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

Example explicit bundle:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --output data/evidence.zip

ebus-evidence verify data/evidence.zip
```

Custom paths, profiles, timezone handling, checkpoint controls and explicit
bundle choices remain available through these commands.

---

## 12. Timezones

ebusd raw-log timestamps do not carry an explicit UTC offset.
`ebus-evidence` therefore does not guess.

If you know the source timezone:

```bash
./evidence collect \
  --source-timezone UTC \
  --display-timezone Europe/Berlin
```

If unsure, omit timezone arguments. The original raw timestamp is preserved.

---

## 13. Update later

Return to **the directory where you cloned the repository** and pull current
code:

```bash
cd /path/to/ebus-evidence
git pull --ff-only
bash install.sh
```

If you used the home-directory example during installation, that path is
`~/ebus-evidence`.

The installer reuses the existing `.venv` when possible and reinstalls the
current checkout.

If the update includes a newer evidence-profile version, no manual JSON editing
or state deletion is needed.

You may immediately inspect/export the old evidence with the new tool:

```bash
./evidence status
./evidence export
```

Those commands preview the rollover read-only. When you next run:

```bash
./evidence collect
```

the tool persists the new active epoch and resumes from the saved raw-log
checkpoint. Do not delete the old state merely because the profile version
changed.

Check:

```bash
./evidence --version
```

---

## 14. Current input boundary

Validated/supported input:

- normal ebusd message-mode raw log, with CRC/ACK/NAK/transaction-framing
  validation before records can become Evidence;
- Docker/native local file;
- copied/static message-mode raw-log file through `import`;
- read-only mounted growing raw-log file through `collect`;
- Home Assistant OS through a file-based workflow.

Not currently supported as the primary evidence input:

- ebusd byte-mode raw logging;
- direct eBUS adapter access;
- automatic live network streaming from another ebusd host;
- direct use of the ebusd client TCP port as the evidence stream.

---

## 15. If something does not work

Start with:

```bash
./evidence doctor
./evidence status
```

For a manual file:

```bash
./evidence doctor --raw /path/to/ebusd.raw --profile hw5103-open-evidence
./evidence status --raw /path/to/ebusd.raw
```

Useful basic checks:

```bash
python3 --version
git --version
ls -lh /path/to/ebusd.raw*
head -n 5 /path/to/ebusd.raw
```

Then use **[Troubleshooting](TROUBLESHOOTING.md)**.

---

## Upstream ebusd

ebusd itself is a separate project:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
