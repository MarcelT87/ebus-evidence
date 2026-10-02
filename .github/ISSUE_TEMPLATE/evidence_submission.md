---
name: Evidence submission
about: Submit a verified ebus-evidence bundle for cross-installation review
title: "Evidence: "
labels: []
assignees: []
---

Thanks for contributing passive eBUS evidence.

## Bundle

Drag and drop **`data/evidence.zip`** here:

<!-- Attach evidence.zip here. Do not attach the complete ebusd.raw file. -->


## Verification

Paste the output of:

```bash
./evidence verify data/evidence.zip
```

```text
PASTE VERIFY OUTPUT HERE
```


## Optional context

System/product model, if known:

```text
optional
```

ebusd environment:

- [ ] Docker
- [ ] native Linux/systemd
- [ ] Home Assistant App/Add-on
- [ ] other

Evidence path:

- [ ] live/growing raw log with `collect`
- [ ] static/copied raw log with `import`

Anything unusual during collection/import:

```text
optional
```


## Privacy check

Before submitting, please confirm:

- [ ] The attached file is `evidence.zip`, not the complete `ebusd.raw`.
- [ ] I did not add `--include-context-raw` unless it was specifically requested and reviewed.
- [ ] I did not paste passwords, tokens, IP addresses, serial numbers or unrelated host configuration.
- [ ] I understand that attachments to this public issue should be treated as publicly shared data.

See [Submit evidence](../../docs/SUBMIT_EVIDENCE.md) for the full submission guide.
