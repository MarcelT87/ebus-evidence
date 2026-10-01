# Installation and first run

This guide is written for users who already have an eBUS installation and want to collect **passive, reproducible evidence** with `ebus-evidence`.

You do not need Home Assistant, MQTT, Proxmox, or an analyzer database.

`ebus-evidence` does not talk to the eBUS adapter and does not send eBUS commands. It reads a raw log that is already written by normal `ebusd`.

If you need help understanding the difference between Docker/native ebusd, USB/network adapters, `ens:`/`enh:`, mDNS, remote hosts, or the ebusd TCP client port, see [ebusd setup matrix](EBUSD_SETUPS.md).

---

## 1. First: which setup do you have?

Choose the closest option.

### A. Normal ebusd in Docker

Examples:

- Docker Compose
- `docker run john30/ebusd ...`

This is supported. The adapter itself may be USB, serial, TCP, UDP, `ens:`, `enh:`, or discovered by ebusd. For `ebus-evidence`, that transport does not matter as long as ebusd writes a message-mode raw log.

### B. Normal ebusd installed directly on Linux

Examples:

- `ebusd.service`
- systemd on Debian, Ubuntu, Raspberry Pi OS, etc.

This is supported. Automatic discovery is implemented; real-world validation of more native installations is still useful.

### C. Normal ebusd runs on another computer

Offline analysis is supported.

Copy the raw log to the computer running `ebus-evidence`, or make it available through a read-only filesystem mount and use `--raw /path/to/ebusd.raw`.

Automatic live following over the network is not implemented yet.

### D. micro-ebusd runs directly on the ESP32 adapter

Do not assume compatibility yet.

micro-ebusd is a separate execution mode on supported ESP32 adapters. Its downloadable/raw log format has not yet been validated against the normal ebusd message-mode format used by this project.

### E. I do not know

On Linux, try:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}' | grep -i ebusd
systemctl status ebusd --no-pager
```

If the first command shows an ebusd container, use the Docker path below.

If the second command shows an active `ebusd.service`, use the native/systemd path below.

If neither applies, you can still use a known raw-log file manually.

---

## 2. Requirements

The easiest supported environment is Linux with:

- Python 3.11 or newer
- Git
- Python virtual environment support
- read access to an ebusd message-mode raw log

Check:

```bash
python3 --version
git --version
```

On Debian/Ubuntu/Raspberry Pi OS, install the usual prerequisites with:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

If `python3 --version` is older than 3.11, install a newer Python version before continuing.

---

## 3. Install ebus-evidence

Choose a directory where you want to keep the program, then run:

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e .
```

Check the installation:

```bash
ebus-evidence --version
ebus-evidence --help
```

When you open a new shell later, return to the repository and reactivate the virtual environment:

```bash
cd ebus-evidence
source .venv/bin/activate
```

### Windows or macOS

Offline analysis of an already copied raw-log file is possible in principle wherever Python 3.11+ works.

Windows PowerShell activates the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Automatic Docker/systemd discovery is primarily intended for Linux.

---

## 4. Try automatic discovery first

If normal ebusd runs on the same Linux host, run:

```bash
ebus-evidence doctor
```

`doctor` is read-only.

It checks whether it can identify a normal ebusd Docker container or native systemd service and locate its configured raw log.

It does not:

- access the eBUS adapter;
- send eBUS telegrams;
- change heating settings;
- modify ebusd configuration;
- read container environment variables.

If `doctor` finds a valid **message-mode** raw log, continue with [Run the first analysis](#8-run-the-first-analysis).

If it reports that raw logging is missing or cannot locate a file, continue below.

---

## 5. Enable a message-mode raw log in Docker ebusd

`ebus-evidence` needs the normal ebusd message log.

Do **not** use byte mode:

```text
--lograwdata=bytes
```

For Docker Compose, a simple example is:

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

This example uses:

- `/rawlog/ebusd.raw` inside the container;
- `/srv/ebusd/rawlog/ebusd.raw` on the Docker host;
- about 100 MiB maximum active raw-log size.

Use a host directory that fits your own installation. The example path is not required.

After changing Docker Compose, recreate/restart the ebusd container using the method you normally use.

Then check on the host:

```bash
ls -lh /srv/ebusd/rawlog/
head -n 5 /srv/ebusd/rawlog/ebusd.raw
```

A normal record looks roughly like:

```text
2026-10-01 10:00:00.000 <1008b507020900...
```

If your host path is different, substitute your real path.

### Important Docker note

A raw file that exists only inside the container is not useful after the container is replaced.

Mount the raw-log directory to the Docker host if you want persistent analysis and restart-safe watch state.

---

## 6. Enable a message-mode raw log in native/systemd ebusd

Normal ebusd supports these raw logging options:

```text
--lograwdata
--lograwdatafile=/var/log/ebusd.raw
--lograwdatasize=102400
```

Add them to the place where **your existing ebusd startup arguments are configured**.

Do not blindly replace a systemd service file from an internet example; ebusd packages and local installations differ.

Restart ebusd using your normal service setup, commonly:

```bash
sudo systemctl restart ebusd
```

Then check:

```bash
ls -lh /var/log/ebusd.raw*
head -n 5 /var/log/ebusd.raw
```

If ebusd cannot create or update the file, fix the directory/file permissions for the user running ebusd.

Again, do **not** configure:

```text
--lograwdata=bytes
```

`ebus-evidence` currently expects message-mode records.

---

## 7. Use a raw log manually

If automatic discovery does not fit your installation, pass the file yourself:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

If a rotated sibling such as `ebusd.raw.old` exists and should be included in offline analysis:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --include-rotated \
  --profile hw5103-open-evidence
```

---

## 8. Run the first analysis

When automatic discovery works:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence
```

With a manual path:

```bash
ebus-evidence analyze \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

To include the normal ebusd rotated `.old` file:

```bash
ebus-evidence analyze \
  --include-rotated \
  --profile hw5103-open-evidence
```

The bundled `hw5103-open-evidence` profile is intentionally narrow. A clean run with zero matches can simply mean that your installation does not contain those identities.

---

## 9. Timestamp timezone

ebusd raw-log timestamps do not carry an explicit UTC offset. `ebus-evidence` therefore does not guess.

If you know that the source timestamps are UTC:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence \
  --source-timezone UTC
```

For a local display timezone:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence \
  --source-timezone UTC \
  --display-timezone Europe/Berlin
```

Use the timezone that is correct for your own installation.

If you are not sure, omit the timezone arguments. The original raw timestamp is preserved.

---

## 10. Optional: passive live watch

Once `doctor` and `analyze` work, you can follow new records:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence
```

Stop with `Ctrl-C`.

For a short test:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --seconds 15
```

Watch reads the raw-log file only. It does not generate bus traffic.

---

## 11. Recommended: persistent evidence state

For longer observation, create a local data directory:

```bash
mkdir -p data/contexts
```

Then run:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

The state keeps compact evidence counts and a restart checkpoint.

The context directory is only used when an explicit rare trigger in the profile fires.

Both `data/` and generated raw/ZIP artifacts are ignored by this repository's `.gitignore` so they are less likely to be committed accidentally.

---

## 12. Create a shareable bundle

State-only bundle:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --output evidence.zip
```

If context captures exist:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --output evidence.zip
```

For a more conservative metadata-only export without raw context payloads:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --no-context-raw \
  --output evidence-metadata.zip
```

Before sharing:

```bash
ebus-evidence verify evidence.zip
```

Expected:

```text
Status: VALID
```

Raw context files contain real eBUS payloads from a small time window. Review them before publishing them.

---

## 13. Update ebus-evidence later

From the repository directory:

```bash
source .venv/bin/activate
git pull --ff-only
pip install -e .
```

Then run:

```bash
ebus-evidence --version
```

---

## 14. What is not supported yet?

Currently not considered a validated input path:

- micro-ebusd downloadable/raw logs;
- ebusd byte-mode raw logging;
- direct eBUS adapter access;
- automatic live streaming from an ebusd host over the network;
- direct use of the ebusd client TCP port as the evidence stream.

The common supported input is a normal **ebusd message-mode raw-log file**.

---

## 15. If something does not work

Start with:

```bash
ebus-evidence doctor
```

or, with an explicit file:

```bash
ebus-evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Useful checks:

```bash
python3 --version
git --version
ls -lh /path/to/ebusd.raw*
head -n 5 /path/to/ebusd.raw
```

Common causes are:

- Python older than 3.11;
- virtual environment not activated;
- missing read permission;
- raw logging not enabled;
- Docker raw directory not mounted to the host;
- byte-mode raw logging instead of message mode;
- an unusual ebusd installation that needs `--raw`;
- a profile that simply does not match the installed devices.

A dedicated troubleshooting guide will collect setup-specific failure cases as the project is tested on more independent installations.

---

## Upstream ebusd references

ebusd itself is a separate project.

Useful upstream documentation:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
- https://github.com/john30/ebusd/blob/master/contrib/docker/docker-compose.example.yaml

`ebus-evidence` does not install or configure ebusd automatically.
