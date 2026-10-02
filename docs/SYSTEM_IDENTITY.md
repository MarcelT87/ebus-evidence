# System identity

Evidence is most useful when it can be tied to a clearly described hardware and firmware combination.

`ebus-evidence` therefore keeps two kinds of information separate:

1. the **declared product name** supplied by the user, for example `Vaillant YOUR-MODEL`;
2. the **observed eBUS device identities** reported by an existing ebusd scan result.

The product name is not used to guess the bus hardware.

---

## Safety boundary

This workflow does **not** start an eBUS scan.

It consumes output that already exists from:

```text
ebusctl scan result
```

Do not run `ebusctl scan` or `ebusctl scan full` merely to create evidence for this project.

If your ebusd installation has no existing scan result, skip system identity for now.

---

## 1. Save the existing scan result

When working inside the `ebus-evidence` checkout, keep local input under `data/`. That directory is ignored by Git.

```bash
mkdir -p data
```

On a system where `ebusctl` is already configured to talk to your normal ebusd instance, save the **existing** scan result:

```bash
ebusctl scan result > data/scan-result.txt
```

Review the file before continuing:

```bash
cat data/scan-result.txt
```

A normal line starts with fields such as:

```text
08;Vaillant;HMU00;0902;5103;...
```

The first five columns are:

```text
address ; manufacturer ; device id ; software version ; hardware version
```

Additional scan columns are deliberately ignored by `ebus-evidence`.

The generated `data/system.json` retains only address, manufacturer, device ID, software version and hardware version from each scan line. Do not manually copy extra scan columns into the system document.

---

## 2. Create system.json

Example for a user-declared Vaillant YOUR-MODEL:

```bash
ebus-evidence system \
  --scan-result data/scan-result.txt \
  --manufacturer Vaillant \
  --model "YOUR-MODEL" \
  --output data/system.json
```

This writes a privacy-minimized document containing only:

- bus address;
- manufacturer;
- device ID;
- software version;
- hardware version;
- optional user-declared product manufacturer/model;
- a deterministic topology SHA-256.

It does not retain the additional scan-result columns.

---

## 3. What the topology signature means

The topology signature is calculated only from the observed device list:

```text
address + manufacturer + device id + SW + HW
```

The user-declared marketing/product name is deliberately **not** part of the signature.

Therefore:

- two technically identical device topologies produce the same signature;
- changing `YOUR-MODEL` to another human label does not change the signature;
- firmware or hardware differences do change the signature.

The signature is intended for grouping comparable systems. It is not a personal installation identifier.

---

## 4. Include it in an evidence bundle

Once you also have evidence state/context:

```bash
ebus-evidence bundle \
  --profile hw5103-open-evidence \
  --state data/evidence-state.json \
  --system data/system.json \
  --output data/evidence.zip
```

Verify:

```bash
ebus-evidence verify data/evidence.zip
```

The verifier checks that:

- `system.json` follows the allowed schema;
- no extra device fields such as serial numbers were added;
- the topology signature matches the contained devices;
- the system document is protected by the bundle checksums.

---

## 5. Current Vaillant research scope

The current bundled evidence profile is focused on Vaillant-family HW5103 research.

System identity is intentionally separate from that profile. This lets future profiles target other Vaillant hardware/firmware combinations without changing the raw-log parser.

---

## Related documentation

- [Installation and first run](INSTALL.md)
- [Community cross-installation test](COMMUNITY_TEST.md)
- [Troubleshooting](TROUBLESHOOTING.md)
