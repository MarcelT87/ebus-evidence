# Community cross-installation test

This is the normal contribution flow for another ebusd user who wants to
produce comparable passive evidence.

> **Current target group:** this first community workflow is aimed at
> **Vaillant-family eBUS installations**. The bundled
> `hw5103-open-evidence` profile contains Vaillant-specific identities from the
> current research.

The goal is not to change the heating system or probe unknown registers.
The tool consumes an already configured ebusd message-mode raw log.

## Safety boundary

The test does not require:

- direct eBUS adapter access from `ebus-evidence`;
- `ebusctl write`;
- arbitrary active `ebusctl read`;
- configuration changes on the heating appliance;
- MQTT publishing;
- Home Assistant;
- an analyzer database.

## 1. Install

Choose any directory where your user can write. The home directory is only the
simple example below; no specific system path is required.

```bash
cd ~   # example only
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence
bash install.sh
```

Alternatively:

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git /path/to/ebus-evidence
cd /path/to/ebus-evidence
bash install.sh
```

After installation use the local launcher:

```bash
./evidence --version
```

## 2. Check the ebusd/raw-log setup

If ebusd runs in Docker or as a native systemd service:

```bash
./evidence doctor
```

Expected outcome is a detected ebusd process plus an existing
**message-mode** raw-log path.

If discovery cannot map the installation:

```bash
./evidence doctor \
  --raw /path/to/ebusd.raw \
  --profile hw5103-open-evidence
```

Do not enable byte-mode logging for this tool.

## 3. Collect persistent evidence

This step is required for the normal shareable ZIP workflow:

```bash
./evidence collect
```

Stop with `Ctrl-C` after the desired observation period.

The command automatically keeps:

```text
data/evidence-state.json
data/contexts/
```

and uses the bundled `hw5103-open-evidence` profile.

A later run of:

```bash
./evidence collect
```

resumes from the saved checkpoint when continuity can be proven.

For a manual **growing/live** raw-log path:

```bash
./evidence collect --raw /path/to/ebusd.raw
```

If another user can only provide a completed/static copy of an existing
message-mode raw log, use the equally shareable offline contribution path:

```bash
./evidence doctor --raw /path/to/ebusd.raw --profile hw5103-open-evidence
./evidence import --raw /path/to/ebusd.raw
./evidence status --raw /path/to/ebusd.raw
./evidence export
```

`import` reads the copied source from beginning to end, does not modify it and
refuses to mix it with an existing evidence state.

Check progress/status:

```bash
./evidence status
```

Important:

> `analyze` is optional historical inspection only. It does not create the
> persistent evidence state used by either `collect -> export` or
> `import -> export`.

## 4. Optional: identify the system

For hardware/firmware comparison, prefer the structured
[System identity](SYSTEM_IDENTITY.md) workflow when an existing
`ebusctl scan result` is already available.

Keep local input/output under ignored `data/`:

```bash
mkdir -p data

./evidence system \
  --scan-result data/scan-result.txt \
  --manufacturer Vaillant \
  --model "YOUR-MODEL" \
  --output data/system.json
```

This command does not start a scan. It keeps only
address/manufacturer/device ID/SW/HW from each scan line.

If no existing scan result is available, do **not** trigger a new scan merely
for this project. Skip system identity; export still works.

## 5. Export the ZIP

Run:

```bash
./evidence export
```

The command automatically uses the collected state and context metadata,
includes `data/system.json` when it exists and is valid, writes:

```text
data/evidence.zip
```

and immediately verifies it.

Expected successful result:

```text
Status .............. VALID
Deterministic ....... yes
Ready to share.
```

Raw context payloads are excluded by default.

## 6. Submit the verified bundle

For normal community contribution, submit:

```text
data/evidence.zip
```

Open a GitHub issue using the **Evidence submission** form and upload the ZIP
in its required `.zip` field.

There is no verifier-output copy/paste step. `./evidence export` already
verifies the generated bundle, and maintainers independently verify incoming
files.

Do not attach the complete `ebusd.raw` file.

The repository is public, so an attached evidence ZIP should be treated as
publicly shared data. See [Submit evidence](SUBMIT_EVIDENCE.md) for the exact
privacy and submission checklist.

## 7. Privacy review

The normal bundle exporter does not add:

- absolute host paths;
- hostnames;
- IP addresses;
- environment variables;
- credentials;
- local resume checkpoint/device/inode data;
- full long-running raw logs.

The shared evidence state retains **absolute timestamps** for observation and
matched evidence. This is intentional because timing is part of reproducible
protocol evidence.

Review the exact observation period before public sharing if it is sensitive.

Raw context is included only after an explicit request:

```bash
./evidence export --include-context-raw
```

Review raw context before posting it publicly.

## 8. Optional offline analysis

To inspect historical raw-log content without creating persistent collection
state:

```bash
./evidence analyze --profile hw5103-open-evidence
```

For known UTC source timestamps:

```bash
./evidence analyze \
  --profile hw5103-open-evidence \
  --source-timezone UTC \
  --display-timezone Europe/Berlin
```

This is useful research output, but it is separate from the normal exportable
`collect -> export` and `import -> export` contribution paths.

## 9. Observation scope

Persistent collection records:

```text
frames_seen
passive_frames
ebusd_initiated_frames
non_frames
skipped
first_frame_timestamp
last_frame_timestamp
```

This matters especially for negative evidence. A value not seen during a short
test is different from a value not seen across a multi-day observation.

## 10. What we compare

The primary cross-installation questions remain factual:

- Is the same request identity present?
- Are response shapes compatible?
- Which raw/decoded variants occur?
- Are rare non-zero values seen?
- Are timestamps/context windows complete?
- Do observations agree across different hardware/software installations?

Frequency alone is not sufficient to promote a protocol meaning.

A semantic name should remain separate from the evidence until it has
independent support.
