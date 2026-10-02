# Community cross-installation test

This is the minimal test flow for another ebusd user who wants to contribute comparable passive evidence.

> **Current target group:** this first community workflow is aimed at **Vaillant-family eBUS installations**. The bundled `hw5103-open-evidence` profile contains Vaillant-specific identities from the current research. Users of other manufacturers are welcome to test basic raw-log compatibility, but should not expect this profile to provide meaningful device coverage yet.

The goal is not to change the heating system or probe unknown registers. The tool consumes an already configured ebusd message-mode raw log.

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

```bash
git clone https://github.com/MarcelT87/ebus-evidence.git
cd ebus-evidence

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 2. Check ebusd discovery

If ebusd runs in Docker or as a native systemd service:

```bash
ebus-evidence doctor
```

Expected outcome is a detected ebusd process plus an existing **message-mode** raw-log path.

If discovery cannot map the installation, use an explicit raw-log path instead. Do not enable byte-mode logging for this tool.

## 3. Run an offline analysis

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence
```

If the ebusd timestamps are known to be UTC, a more useful comparison is:

```bash
ebus-evidence analyze \
  --profile hw5103-open-evidence \
  --source-timezone UTC \
  --display-timezone Europe/Berlin
```

For other installations, replace the display timezone as appropriate.

## 4. Optional passive watch

Create a local data directory:

```bash
mkdir -p data/contexts
```

Then:

```bash
ebus-evidence watch \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts
```

Stop with Ctrl-C.

The bundled HW5103 profile currently captures context only for explicitly configured rare non-zero HMU `/a80e` or `/ba08` observations.

## 5. Identify the system

For hardware/firmware comparison, prefer the structured [System identity](SYSTEM_IDENTITY.md) workflow when an existing `ebusctl scan result` is available.

Keep the input and generated identity under the ignored local `data/` directory:

```bash
mkdir -p data

ebus-evidence system \
  --scan-result data/scan-result.txt \
  --manufacturer Vaillant \
  --model "105/6 A" \
  --output data/system.json
```

Replace the example manufacturer/model with the product information that is actually known for the installation.

This command does not start a scan. It reads the supplied file and keeps only address/manufacturer/device ID/SW/HW from each scan line.

If no existing scan result is available, do **not** trigger a new scan merely for this project. Skip `--system` in the bundle step.

Useful additional human-supplied context can still include:

```text
heat-pump / boiler family:
controller:
ebusd version:
configuration source/version:
whether raw timestamps are UTC or local time:
rough observation duration:
```

Do not include passwords, access tokens, network addresses or unrelated Home Assistant configuration.

## 6. Create a shareable bundle

Normal complete bundle when `data/system.json` exists:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --system data/system.json \
  --output data/evidence.zip
```

If no system identity is available, omit the `--system data/system.json` line.

Raw context payloads are excluded by default. Context metadata can still be included.

A state-only bundle is valid when no context directory is being used:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --output data/evidence.zip
```

Only if you intentionally want to include reviewed raw context payloads:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --system data/system.json \
  --include-context-raw \
  --output data/evidence-with-context-raw.zip
```

Again, omit the `--system` line if no system identity exists.

## 7. Verify before sharing

```bash
ebus-evidence verify data/evidence.zip
```

Expected:

```text
Status: VALID
```

A bundle created directly by the tool should also report:

```text
Deterministic layout: yes
```

## 8. Privacy review

The bundle exporter deliberately omits local resume metadata and does not add:

- absolute host paths;
- hostnames;
- IP addresses;
- environment variables;
- credentials;
- full long-running raw logs.

The generated system identity contains only the approved technical identity fields plus the optional user-declared product manufacturer/model and the topology signature.

The shared evidence state retains **absolute timestamps** for the observation window and matched evidence. This is intentional because timing is part of reproducible protocol evidence. If the exact dates/times of the observation are sensitive, review that information before public sharing. New bundles disclose this explicitly in `manifest.json` as:

```text
absolute_timestamps_included: true
```

If small context `.raw` files are explicitly included, they contain actual eBUS payloads from the bounded trigger window. Review them before posting publicly.

For the first public exchange, use the default bundle behavior. Raw context is excluded unless `--include-context-raw` is explicitly supplied.

## 9. Observation scope

A persistent watch state now records how much bus traffic was actually observed:

```text
frames_seen
passive_frames
ebusd_initiated_frames
non_frames
skipped
first_frame_timestamp
last_frame_timestamp
```

These counters are saved together with the watch checkpoint, so a clean resume does not silently double-count already persisted data.

This matters especially for negative evidence. For example:

```text
value X was not observed
```

must be interpreted together with the number of complete frames and the observed time span. A short test and a multi-day observation are not equivalent.

No duration is fabricated when the raw timestamp timezone is unknown. The original first/last frame timestamps are preserved; timezone-aware UTC/display forms are included when the source timezone was explicitly supplied.

## 10. What we compare

The primary cross-installation questions are factual:

- Is the same request identity present?
- Are response shapes compatible?
- Which raw/decoded variants occur?
- Are rare non-zero values seen?
- Are timestamps/context windows complete?
- Do observations agree across different hardware/software installations?

Frequency alone is not sufficient to promote a protocol meaning.

A semantic name should remain separate from the evidence until it has independent support.
