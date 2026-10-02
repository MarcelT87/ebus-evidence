# Home Assistant

This guide is for users who run ebusd together with Home Assistant.

> **Current research scope:** the bundled `hw5103-open-evidence` profile is currently aimed at Vaillant-family systems. Home Assistant only changes the installation path; it does not make the current evidence profile manufacturer-independent.

The first question is **which Home Assistant installation you have**.

Home Assistant currently recommends two main installation types:

- **Home Assistant OS** — the appliance-style installation with Home Assistant Apps (formerly commonly called add-ons);
- **Home Assistant Container** — Home Assistant runs as a container on a Linux host that you manage yourself.

These require different `ebus-evidence` workflows.

---

## 1. Home Assistant OS

Typical examples:

- Home Assistant Green;
- Home Assistant Yellow;
- Home Assistant OS on Raspberry Pi;
- Home Assistant OS in a VM, for example on Proxmox.

If you installed ebusd as a Home Assistant **eBUSd App/Add-on**, do **not** start by trying to install `ebus-evidence` directly into the Home Assistant OS host.

The current recommended workflow is:

```text
Home Assistant OS
      ↓
eBUSd App
      ↓
message-mode raw log
      ↓
copy/read the raw-log file
      ↓
run ebus-evidence on a normal supported computer
```

This keeps the Home Assistant appliance untouched. The documented beginner
installation is currently validated on Linux; other Python environments may
work but are not the primary supported path yet.

### Common eBUSd App

The commonly used Home Assistant eBUSd App from the `LukasGrebe/ha-addons` repository packages the normal, unmodified ebusd binary inside a Home Assistant supervised container.

Its current documentation allows additional ebusd command-line options and provides a persistent App config directory.

For that App, add these three entries as separate **Additional ebusd options / commandline_options**:

```text
--lograwdata
--lograwdatafile=/config/ebusd.raw
--lograwdatasize=102400
```

Do **not** use:

```text
--lograwdata=bytes
```

Restart the eBUSd App after changing its configuration.

The App's `/config` directory is persistent and is currently mapped by the App to its Home Assistant App config folder.

You should then have:

```text
/config/ebusd.raw
```

inside the eBUSd App.

The App documentation describes access to its config folder through:

- Studio Code Server;
- Advanced SSH & Web Terminal;
- Samba.

The exact Home Assistant host path used by this particular App is currently:

```text
/addon_configs/2ad9b828_ebusd/
```

That path belongs to this specific third-party App and may change in a future App version. Prefer the App's own current documentation if it differs.

### What to do with the raw log

The simplest beginner workflow is to copy `ebusd.raw` to the computer where you want to run `ebus-evidence`.

For example, after copying it to your home directory:

```text
~/ebusd.raw
```

install `ebus-evidence` on that computer using [Installation and first run](INSTALL.md), then run:

```bash
./evidence doctor \
  --raw ~/ebusd.raw \
  --profile hw5103-open-evidence
```

Then:

```bash
./evidence analyze \
  --raw ~/ebusd.raw \
  --profile hw5103-open-evidence
```

For a first test, this copied-file workflow is preferred over trying to create a permanent live connection into Home Assistant OS.

### Important: copied files vs persistent collection

A one-time copied raw log is excellent for `doctor` and offline `analyze`.

The beginner `collect -> export` workflow is a **persistent follower**: a fresh
collection starts at the current end of a readable raw-log file and then follows
new records, keeping a continuity checkpoint.

Therefore a static copied file is not currently a historical import into
persistent evidence state.

To produce a meaningful persistent evidence ZIP, run `collect` where the raw
file remains readable and continues to grow. Do not repeatedly replace the file
behind an existing checkpoint.

A future explicit historical-import workflow may address this use case; the
current documentation does not pretend that a one-time static copy is
equivalent to live/resumable collection.

---

## 2. Home Assistant Container

If Home Assistant itself runs as a Docker container on a normal Linux machine, you manage the underlying Linux host yourself.

In that case, **Home Assistant does not determine the ebus-evidence installation**.

Instead ask:

> Where does ebusd run?

### ebusd is another Docker container on the same Linux host

Install `ebus-evidence` on the Linux host and follow the normal Docker instructions:

- [Installation and first run](INSTALL.md)
- [ebusd setups](EBUSD_SETUPS.md#docker-ebusd)

### ebusd runs natively on the same Linux host

Install `ebus-evidence` on that Linux host and follow:

- [native/systemd ebusd](EBUSD_SETUPS.md#nativesystemd-ebusd)

### ebusd runs on another machine

Use the file-based path:

- copy the message-mode raw log; or
- mount the raw-log directory read-only.

Then pass the file with `--raw`.

---

## 3. I use Home Assistant but do not know which type

A useful first clue is whether Home Assistant provides an **Apps** section and manages Apps for you.

If you use Home Assistant Green, Yellow, or installed Home Assistant OS as an appliance/VM, you are normally using **Home Assistant OS**.

If you manually started Home Assistant with Docker or Docker Compose on a Linux server, you are using **Home Assistant Container**.

If still unsure, check Home Assistant:

```text
Settings -> System -> Repairs -> three-dot menu -> System information
```

Use the installation information shown there before continuing.

---

## 4. Why not install ebus-evidence directly into Home Assistant OS?

Home Assistant OS is intentionally managed as an appliance.

`ebus-evidence` is currently a normal Python command-line project, not a Home Assistant App.

For a beginner, installing development tools into unrelated App containers or relying on temporary container modifications would be fragile and difficult to maintain.

The current safe approach is therefore:

```text
HA OS produces raw log
        ↓
raw log leaves HA OS as a file
        ↓
ebus-evidence analyzes the file elsewhere
```

A dedicated Home Assistant App could be considered later only if real users show that the file-based workflow is too inconvenient.

---

## 5. What Home Assistant is not required for

`ebus-evidence` does not use Home Assistant entities, automations, dashboards or MQTT as its evidence source.

It only needs the ebusd message-mode raw log.

Home Assistant is therefore an **installation environment**, not part of the evidence format.

---

## Related documentation

- [Installation and first run](INSTALL.md)
- [ebusd setups](EBUSD_SETUPS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Community cross-installation test](COMMUNITY_TEST.md)

Current external references:

- https://www.home-assistant.io/installation/
- https://www.home-assistant.io/faq/ha-vs-hassio/
- https://github.com/LukasGrebe/ha-addons
- https://github.com/LukasGrebe/ha-addons/blob/main/ebusd/DOCS.md
