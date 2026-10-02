# Troubleshooting

This guide starts from the **symptom you can see** and works toward the likely
cause.

`ebus-evidence` is designed to be read-only. Troubleshooting should not
require changing heating parameters or actively probing unknown eBUS registers.

## Fast path

For the normal beginner workflow, start with the matching step:

```text
installation / launcher problem -> bash install.sh
raw-log / ebusd problem          -> ./evidence doctor
collection / resume problem      -> ./evidence status
ZIP/export problem               -> ./evidence export
existing ZIP verification        -> ./evidence verify FILE.zip
```

The detailed reference below keeps the explicit expert commands as well.

---

# 1. `./evidence` is missing or not executable

From the repository directory run:

```bash
bash install.sh
```

Then:

```bash
./evidence --version
```

The bootstrap installer creates/reuses `.venv`, installs the current checkout
and marks the local launcher executable.

If you prefer the explicit Python environment:

```bash
source .venv/bin/activate
ebus-evidence --version
```

On Windows PowerShell, where the local shell launcher is not the primary path:

```powershell
.venv\Scripts\Activate.ps1
ebus-evidence --version
```

---

# 1A. `.venv` does not exist

Check the system Python first:

```bash
python3 --version
command -v python3
```

`ebus-evidence` requires Python 3.11 or newer.

Normally just rerun:

```bash
bash install.sh
```

For manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Debian/Ubuntu, if creating the virtual environment reports that `venv` or
`ensurepip` is unavailable:

```bash
sudo apt install python3-venv
```

---

# 2. `python3 -m venv` fails

Typical Debian/Ubuntu error:

```text
The virtual environment was not created successfully...
ensurepip is not available
```

Install the venv package:

```bash
sudo apt update
sudo apt install -y python3-venv
```

Then retry:

```bash
python3 -m venv .venv
```

---

# 3. Python is too old

Check:

```bash
python3 --version
```

The project currently requires Python 3.11 or newer.

If the system Python is older, install a newer Python version using the method appropriate for your operating system before creating the virtual environment.

Do not try to work around the requirement by editing `pyproject.toml`.

---

# 4. Git is missing

Check:

```bash
git --version
```

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y git
```

---

# 5. `doctor` does not find ebusd

Run:

```bash
ebus-evidence doctor
```

If automatic discovery fails, first determine where normal ebusd runs.

If ebusd runs as a **Home Assistant OS eBUSd App/Add-on**, automatic Docker/systemd discovery from a separate computer is not the expected path. Use the file-based [Home Assistant guide](HOME_ASSISTANT.md) instead.

## Docker check

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}' | grep -i ebusd
```

If this shows an ebusd container, see [ebusd setup matrix](EBUSD_SETUPS.md#docker-ebusd).

If `docker ps` itself returns a permission error, automatic Docker discovery cannot work for that user yet. Fix Docker access using the normal permission model of your Docker installation, or use an explicit readable host raw-log path with `--raw`.

Do not make the Docker socket world-writable just to make discovery work.

## systemd check

```bash
systemctl status ebusd --no-pager
```

If this shows an active service, see [ebusd setup matrix](EBUSD_SETUPS.md#nativesystemd-ebusd).

## Neither is found

You may have:

- ebusd on another computer;
- ebusd started manually;
- an unusual container/service layout;

If you already know the raw-log file path, bypass discovery:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

---

# 6. ebusd is found, but raw logging is disabled

`ebus-evidence` needs normal ebusd **message-mode raw logging**.

Required ebusd options are conceptually:

```text
--lograwdata
--lograwdatafile=FILE
--lograwdatasize=SIZE
```

Do not use:

```text
--lograwdata=bytes
```

For Docker and native examples, see:

- [Installation and first run](INSTALL.md)
- [Home Assistant](HOME_ASSISTANT.md)
- [ebusd setup matrix](EBUSD_SETUPS.md)

After enabling logging, verify that the file exists and grows.

---

# 7. The raw-log file does not exist

Check the configured path.

Example:

```bash
ls -lh /path/to/
```

Then check the running ebusd arguments.

For native Linux:

```bash
ps -ef | grep '[e]busd'
```

For Docker:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}'
```

If using Docker, remember that the path **inside the container** and the path **on the host** may be different.

Example:

```text
container:
/rawlog/ebusd.raw

host:
/srv/ebusd/rawlog/ebusd.raw
```

The host directory must be mounted into the container if you want the file to survive container recreation and be directly readable from the host.

---

# 8. The raw-log file exists but does not grow

Check the size twice:

```bash
ls -lh /path/to/ebusd.raw
sleep 10
ls -lh /path/to/ebusd.raw
```

Also inspect the newest lines:

```bash
tail -n 10 /path/to/ebusd.raw
```

Possible causes:

- ebusd is not currently receiving bus traffic;
- raw logging was configured but the running process was not restarted/recreated;
- the configured log path differs from the file being checked;
- ebusd cannot write to the target directory;
- a container is writing to a different internal path.

For Docker, inspect the mounted directories in your own Compose/container configuration.

---

# 9. Permission denied reading the raw log

Test:

```bash
head -n 1 /path/to/ebusd.raw
```

If this returns `Permission denied`, `ebus-evidence` will not be able to read it either.

Inspect permissions:

```bash
ls -l /path/to/ebusd.raw
ls -ld /path/to
```

Use the normal Linux permission/group model for your installation.

Avoid solving this by making sensitive directories world-writable.

For a remote installation, a read-only copy or read-only filesystem mount is sufficient for offline analysis.

---

# 10. `doctor` says byte mode is configured

The current parser intentionally does not support:

```text
--lograwdata=bytes
```

Enable normal message mode instead:

```text
--lograwdata
```

A message-mode line looks roughly like:

```text
2026-10-01 10:00:00.000 <1008b507020900...
```

---

# 11. The raw log contains `<00`, `<01`, `<20` or other very short records

That can happen in ebusd message-mode logging.

`ebus-evidence` treats short valid raw records separately as `non_frames`.

They are **not automatically parser errors** and should not be assigned protocol semantics merely because they occur frequently.

Example watch summary:

```text
non_frames=10
skipped=0
```

This can be a clean result.

---

# 12. `skipped` is greater than zero

`skipped` is different from `non_frames`.

A skipped record means a completed raw record could not be parsed as expected.

Run a short watch and inspect the bounded skip samples printed by the tool.

Useful information to report in an issue:

- exact `ebus-evidence --version`;
- the skip reason;
- one or two displayed sample records;
- whether the source is normal ebusd message mode;
- ebusd version if known.

Do not post an entire private long-running raw log unless you have reviewed it first.

---

# 13. `partial_tail=1`

This usually means the watch stopped while the last raw-log record was still being written.

It is tracked separately from malformed completed records.

A single `partial_tail` exactly at process shutdown is not automatically a problem.

If partial tails appear continuously during normal operation, report the behavior with the raw-log source/setup.

---

# 14. Analysis shows zero matches

This does not necessarily mean the parser is broken.

The bundled profile:

```text
hw5103-open-evidence
```

is deliberately narrow.

Zero matches can mean:

- your system does not contain those device identities;
- the relevant telegrams did not occur in the captured period;
- your hardware/software family differs;
- you are using the wrong raw-log file;
- the raw log contains no complete message-mode telegrams.

First confirm that the file has real traffic:

```bash
head -n 20 /path/to/ebusd.raw
tail -n 20 /path/to/ebusd.raw
```

Then run:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Do not interpret frequency or absence alone as proof of a protocol meaning.

---

# 15. Timestamps look wrong by one or two hours

ebusd raw-log timestamps do not carry an explicit UTC offset.

`ebus-evidence` therefore does not guess the source timezone.

If you know the source timestamps are UTC:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence \
  --source-timezone UTC \
  --display-timezone Europe/Berlin
```

If you are unsure which timezone ebusd used, omit the timezone arguments and keep the raw timestamp unchanged.

Do not "correct" timestamps by adding a fixed hour offset manually.

---

# 16. Watch starts at the current end and ignores old data

This is expected when watch has no persisted checkpoint.

A fresh stateless watch follows **new records only**.

For historical data, use:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence
```

For restartable long-running watch, use a state file:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json
```

---

# 16A. A timed diagnostic watch shows a larger raw-timestamp interval

Normal beginner collection has no timer and runs until Ctrl-C.

The optional `--seconds` argument is an advanced/testing wall-clock runtime
limit for the watch process, not a source-data time window.

With a persistent state, watch resumes at the saved checkpoint. If raw-log data accumulated while watch was stopped, the next run processes that backlog before or while following the live end.

For example, a short timed diagnostic run can legitimately process a much
larger raw-log timestamp interval if that amount of history accumulated since
the previous checkpoint.

This is intentional. It preserves observation continuity instead of silently jumping to the current end and losing the paused interval.

Check the summary:

```text
resume=active
```

means the saved active-log checkpoint was resumed successfully.

---

# 17. Watch reports a checkpoint/resume error

The persisted state contains a checkpoint that identifies the raw-log history.

Watch refuses to silently claim continuity when it cannot prove that the current active file or its `.old` sibling matches the saved checkpoint.

Possible causes:

- more raw-log rotations occurred while watch was stopped;
- files were deleted or replaced;
- the raw-log path now points to a different history;
- the filesystem reused an inode but the content anchor differs.

If the missing interval is acceptable and you intentionally want to establish a new starting point:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --reset-checkpoint
```

This records a continuity reset.

Do not use `--reset-checkpoint` merely to hide an unexplained gap.

---

# 18. Profile version changed / rollover pending

A state file remains bound to one profile name, but newer versions of that same
profile can roll forward safely.

Typical status after updating:

```text
Evidence state ...... profile rollover pending (v2 -> v3)
Rollover preview .... read-only; collect/watch persists it
```

If the old state already contains evidence, `status` can still report
`Ready to export YES`. A normal:

```bash
./evidence export
```

creates the new-profile bundle from an in-memory rollover preview and does not
modify the local state. This keeps static-import-only installations usable.

The next normal writer command:

```bash
./evidence collect
```

persists the same rollover under the state-writer lock. The tool then:

- archives the old profile/version observation as a historical epoch;
- keeps the existing raw-log checkpoint;
- starts the new profile version with 0 active-epoch frames;
- does not replay old traffic into new checks.

Before or after persistence, the bundle retains the historical epoch and the
new active profile starts with zero inherited coverage.

Old context metadata stays on disk but is excluded from current-profile export
unless it belongs to the active profile version.

The tool still refuses unsafe cases:

- a different profile name;
- a profile downgrade;
- changed profile semantics without a version bump;
- malformed state/epoch metadata.

Do not edit the state JSON to bypass those checks. If you intentionally want a
completely separate observation, choose a new `--state` path instead.

---

# 19. Context directory stays empty

That can be completely normal.

Context capture only happens for checks with an explicit `context` trigger in the profile.

The current bundled HW5103 profile intentionally uses rare conditions such as a non-zero value for selected HMU checks.

If the watched values remain zero:

```text
context_triggers=0
contexts=0
```

is expected.

Do not generate active bus traffic merely to force a context capture.

---

# 20. Context bundle says `pre_window_complete=false`

This means the trigger occurred before enough historical records had accumulated in the in-memory context buffer.

Typical case:

- watch started;
- a rare trigger happened less than 120 seconds later.

The bundle is still explicit about the limitation.

A later trigger after the watch has been running long enough can have a complete pre-window.

---

# 21. Context bundle says `post_window_complete=false`

This means collection ended before the configured post-trigger window was fully observed.

Typical causes:

- user stopped watch with Ctrl-C;
- process exited;
- host restarted.

The bundle remains useful as partial evidence, but it must not be presented as having a complete post-window.

---

# 22. Bundle creation says the state file does not exist

Check:

```bash
ls -lh data/evidence-state.json
```

Then create a state by running watch with:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json
```

The bundle command intentionally refuses to invent an empty state when an explicit `--state` path is wrong.

---

# 23. Bundle creation says no evidence was found

A bundle needs at least:

- an existing evidence state, or
- at least one valid context metadata file.

An empty context directory alone is not evidence.

Create a state with watch first, or provide a context directory that actually contains captures.

---

# 24. `verify` reports checksum mismatch

Example:

```text
INVALID: checksum mismatch for evidence/state.json
```

The bundle contents changed after its checksums were created.

Possible causes:

- manual editing inside the ZIP;
- incomplete/corrupt transfer;
- a damaged archive;
- repackaging that also changed file bytes.

Do not trust the bundle as unchanged evidence.

Ask the sender to create and verify a fresh bundle.

---

# 25. `verify` says VALID but deterministic layout is no

Example:

```text
Status: VALID
Deterministic layout: no (content integrity still valid)
```

This means:

- all checked member contents and checksums are still valid;
- the ZIP container itself is no longer in the canonical ordering/timestamp layout produced by `ebus-evidence`.

A common cause is unpacking and repacking the archive without changing the contained files.

This is intentionally different from a checksum failure.

---

# 26. Does a bundle contain raw context files by default?

No.

Current bundles exclude context `.raw` files unless you explicitly request them.

The normal public-sharing command is:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --output data/evidence.zip
```

If you deliberately need the reviewed raw context as well:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --include-context-raw \
  --output data/evidence-with-context-raw.zip
```

Raw context payloads can contain device-specific bus data. Review them before public sharing.

---

# 27. Docker container is recreated and the raw log disappears

The raw-log directory should be mounted to the Docker host.

Example:

```yaml
volumes:
  - /srv/ebusd/rawlog:/rawlog
```

If the log only exists in the container filesystem, replacing the container can remove that history.

Keep persistent raw logs outside the disposable container layer.

---

# 28. Docker discovery finds ebusd but cannot map the raw path to the host

Automatic mapping relies on Docker mount metadata.

Possible causes:

- raw log lives only inside the container;
- file is under a path that is not host-mounted;
- unusual container runtime/setup;
- mount configuration changed.

Use a host-mounted raw-log directory, or pass a known host path manually:

```bash
ebus-evidence doctor \
  --raw /host/path/ebusd.raw \
  --profile hw5103-open-evidence
```

---

# 29. ebusd is on another host and I only know port 8888

Port 8888 is normally the **ebusd client interface**, used by tools such as `ebusctl`.

It is not currently the primary evidence transport for this project.

Recommended current options:

1. copy the normal message-mode raw log;
2. make the raw-log directory available through a secure read-only filesystem mount.

See [ebusd setup matrix](EBUSD_SETUPS.md#ebusd-on-another-computer).

---

# 30. Tests fail after updating

Activate the development environment and install development dependencies:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

Also check:

```bash
git status
git rev-parse HEAD
python --version
```

If you report a failing test, include:

- commit SHA;
- Python version;
- failing test name;
- full traceback for that test.

Do not include unrelated private configuration.

---

# 31. I accidentally created raw logs, ZIPs or states inside the repository

The current `.gitignore` excludes common local/runtime artifacts such as:

- `data/`;
- `contexts/`;
- `*.raw`;
- `*.zip`;
- databases;
- environment files;
- private-note directories.

Check before committing:

```bash
git status
```

If Git already tracks a file, adding it to `.gitignore` does not automatically remove it from history or tracking.

Review the file before deciding how to remove it.

---

# 32. What should I include in a bug report?

Useful:

```text
ebus-evidence version:
commit SHA:
Python version:
operating system:
ebusd installation: Docker / native / other
ebusd version if known:
command that failed:
exact error:
small reviewed sample if needed:
```

Avoid:

- passwords;
- tokens;
- Wi-Fi credentials;
- private keys;
- unrelated network details;
- whole private raw logs unless necessary and reviewed.

---

# 33. Safe diagnostic command block

For a typical Linux installation, this produces a useful first diagnostic without active eBUS access:

```bash
set -u

echo "=== SYSTEM ==="
uname -srm
python3 --version
git --version

echo
echo "=== EBUS-EVIDENCE ==="
ebus-evidence --version

echo
echo "=== DOCTOR ==="
ebus-evidence doctor || true

echo
echo "=== DOCKER EBUSd ==="
docker ps --format '{{.Image}}' 2>/dev/null | grep -i ebusd || true

echo
echo "=== SYSTEMD EBUSd ==="
systemctl is-active ebusd 2>/dev/null || true
```

Review all output before posting it publicly.

---

# 34. `import` says an evidence state already exists

Example:

```text
error: existing evidence state found: data/evidence-state.json
```

This is deliberate. Static import does not silently combine a copied historical
file with an existing live/imported observation history.

Use a fresh checkout/state location, archive the previous local `data/`
directory, or choose an explicit fresh `--state` and empty `--context-dir`.

Do not delete evidence you still need merely to make the command continue.

---

# 35. `import` says the raw source changed during import

A static import requires the source file to remain unchanged from beginning to
end. This error usually means the supplied path points at the **live ebusd raw
log**, which continued to grow during processing.

For a live/growing file use:

```bash
./evidence collect --raw /path/to/live/ebusd.raw
```

For historical import, first make a stable copy and import the copy:

```bash
cp /path/to/live/ebusd.raw /tmp/ebusd-copy.raw
./evidence import --raw /tmp/ebusd-copy.raw
```

The import never modifies the source itself.

---

# 36. `import` reports non-frames such as `short_fragment` or `truncated_request`

The importer distinguishes complete parsed frames from incomplete/non-frame raw
records.

Examples include:

- `short_fragment` — too few bus bytes to form a complete frame;
- `truncated_request` — the telegram declares more request bytes than are
  actually present.

These are counted explicitly as non-frames rather than silently treated as
valid evidence frames.

A small number can occur naturally in real long-running raw logs. A successful
import should still show `Skipped = 0` unless an actually unsupported/malformed
record type is encountered.

Do not edit the source raw log merely to remove these records.

---

# 37. Collection/import says the evidence state is already in use

Example:

```text
error: evidence state is already in use by another writer: data/evidence-state.json
```

This is a safety check. Only one state-writing command may use a given evidence
state at a time.

The protected commands are:

- `./evidence collect`;
- `./evidence import`;
- expert `ebus-evidence watch --state ...`.

Check whether another collection/import/watch process is still running. Stop
that process normally, or use a genuinely different `--state` when you intend
to create a separate observation.

A hidden file similar to:

```text
data/.evidence-state.json.writer.lock
```

may exist even when no writer is running. This is normal. The file itself is
not the lock; the operating system owns/releases the actual advisory lock when
the process starts/exits or crashes.

Do **not** delete the file as a way to bypass an active writer. If no writer is
running and the error persists, check filesystem permissions and whether the
state directory is on an unusual filesystem with incompatible locking
semantics.

---

# Related documentation

- [Installation and first run](INSTALL.md)
- [ebusd setup matrix](EBUSD_SETUPS.md)
- [Community cross-installation test](COMMUNITY_TEST.md)
