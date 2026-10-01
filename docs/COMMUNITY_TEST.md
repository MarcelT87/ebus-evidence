# Community cross-installation test

This is the minimal test flow for another ebusd user who wants to contribute comparable passive evidence.

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

## 5. Create a shareable bundle

With both state and context directory:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --output evidence.zip
```

If there are no context captures yet, a state-only bundle is valid:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --output evidence.zip
```

For metadata/aggregates without raw context payloads:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --context-dir data/contexts \
  --no-context-raw \
  --output evidence-metadata.zip
```

## 6. Verify before sharing

```bash
ebus-evidence verify evidence.zip
```

Expected:

```text
Status: VALID
```

A bundle created directly by the tool should also report:

```text
Deterministic layout: yes
```

## 7. Privacy review

The bundle exporter deliberately omits local resume metadata and does not add:

- absolute host paths;
- hostnames;
- IP addresses;
- environment variables;
- credentials;
- full long-running raw logs.

If small context `.raw` files are present, they contain actual eBUS payloads from the bounded trigger window. Review them before posting publicly.

For the most conservative first exchange, use `--no-context-raw`.

## 8. What to report with the bundle

Useful human-supplied installation context is intentionally kept separate from automatic collection.

Please report only what you are comfortable sharing, for example:

```text
heat-pump / boiler family:
controller:
known module addresses:
device HW/SW versions if already known:
ebusd version:
configuration source/version:
whether raw timestamps are UTC or local time:
rough observation duration:
```

Do not include passwords, access tokens, network addresses or unrelated Home Assistant configuration.

## 9. What we compare

The primary cross-installation questions are factual:

- Is the same request identity present?
- Are response shapes compatible?
- Which raw/decoded variants occur?
- Are rare non-zero values seen?
- Are timestamps/context windows complete?
- Do observations agree across different hardware/software installations?

Frequency alone is not sufficient to promote a protocol meaning.

A semantic name should remain separate from the evidence until it has independent support.
