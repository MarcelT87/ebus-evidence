# Contributing

Thanks for helping improve `ebus-evidence`.

The project deliberately keeps a narrow safety boundary: it turns existing
ebusd message-mode raw logs into passive evidence. Contributions must preserve
that boundary.

## Evidence contributions

Do not commit evidence ZIPs or raw logs to the repository.

Use the GitHub **Evidence submission** issue form and upload only the generated:

```text
data/evidence.zip
```

Normal submissions must not contain a complete `ebusd.raw` or unreviewed raw
context.

## Code contributions

Please use a pull request rather than committing directly to `main`.

Before opening a PR:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

Changes that affect public behavior should include tests and, when relevant,
documentation.

## Safety rules

A contribution must not add:

- direct eBUS adapter access;
- eBUS writes or telegram injection;
- active probing solely to create evidence;
- automatic heating-control behavior;
- automatic MQTT publishing or cloud upload;
- credentials, private logs, local environment notes or private research
  handoffs.

Do not add semantic protocol claims merely because a value is frequent.
Evidence extraction and semantic interpretation remain separate concerns.

## Repository hygiene

Do not commit generated runtime data such as:

- `data/`;
- `*.raw`;
- `*.zip`;
- databases;
- local credentials or environment files.

Keep PRs focused. Prefer one reviewed behavior change per PR.

## Security

For vulnerabilities or potentially sensitive findings, follow
[SECURITY.md](SECURITY.md) instead of posting details in a normal public issue.
