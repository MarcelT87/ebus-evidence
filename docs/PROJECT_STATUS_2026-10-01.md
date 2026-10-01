# ebus-evidence — Projektstand und nächstes Vorgehen

**Stand:** 2026-10-01  
**Projekt:** `MarcelT87/ebus-evidence`  
**Dokumentierter main vor diesem Statusdokument:** `85b25b350f5cc58922f623bc31ca36c311f2c83c`  
**Aktuell validierte Testsuite:** 74 Tests grün

---

## 1. Kurzfassung

`ebus-evidence` hat inzwischen einen belastbaren technischen Kern.

Die validierte Kette ist:

```text
bestehendes ebusd Message-Mode-Rawlog
        ↓
read-only Discovery oder expliziter Dateipfad
        ↓
Offline-Analyse / passiver Live-Watch
        ↓
kompakter persistenter Evidence-State
        ↓
Resume mit Offset + Dateisystem-ID + SHA-256-Inhaltsanker
        ↓
explizite seltene Context-Trigger
        ↓
kleine reproduzierbare Raw-Kontextfenster
        ↓
deterministisches Share-Bundle
        ↓
Bundle-Verifikation beim Empfänger
```

Der Kern soll vorerst **nicht weiter mit Infrastruktur überladen** werden.

Der wichtigste nächste Entwicklungsschritt ist **Benutzerfreundlichkeit und Installationsabdeckung**:

1. Ein Anfänger muss erkennen können, welche ebusd-Variante er hat.
2. Docker/native und USB/TCP/UDP/mDNS müssen sauber getrennt erklärt werden.
3. Es muss klar sein, dass die Adapter-Verbindung für `ebus-evidence` weitgehend egal ist.
4. micro-ebusd muss als eigener Produkttyp behandelt werden.
5. Eine zweite unabhängige Installation soll den Cross-Installation-Workflow real testen.

---

# 2. Projektziel

Das Projekt soll **keinen zweiten ebusd und keinen zweiten großen Analyzer** bauen.

Ziel ist:

> Vorhandene passive eBUS-Daten aus ebusd reproduzierbar in kleine, überprüfbare und vergleichbare Evidence-Artefakte umzuwandeln.

Wichtige Prinzipien:

- passiv / read-only;
- keine automatischen semantischen Namen;
- keine Confidence-Scores;
- keine Promotion nur durch Häufigkeit;
- keine aktiven Reads/Writes nur zur Evidenzerzeugung;
- keine direkte Adaptersteuerung;
- deterministische Profile;
- Interpretation bleibt getrennt von Evidence;
- Cross-Installation-Evidence ist wertvoller als wiederholte lokale Beobachtung.

---

# 3. Aktueller technischer Stand

## 3.1 Eingabe

Aktuell unterstützt:

- normales **ebusd Message-Mode-Rawlog**;
- aktive Datei;
- optional `.old` bei Offline-Analyse;
- Live-Follow;
- Rename/Create-Rotation im Watch;
- explizite Zeitzonenbehandlung;
- eBUS Byte-Unescaping;
- normalisierte Frames.

Nicht unterstützt:

- `--lograwdata=bytes`;
- beliebige Fremdformate;
- direkte Adapterdaten;
- generische JSONL-Eingabe;
- micro-ebusd-Logformat, solange nicht separat validiert.

---

## 3.2 Discovery

Implementiert:

- Docker-ebusd Discovery;
- Docker-Mount-Auflösung Containerpfad → Hostpfad;
- native/systemd Discovery;
- manuelles `--raw FILE` als Fallback.

Real validiert:

- Docker.

Noch real zu validieren:

- native/systemd auf einer unabhängigen Installation.

---

## 3.3 Analyse

Implementiert:

- YAML-Profile;
- source/target/PB-SB/request Matching;
- request prefix Matching;
- einfache Decoder;
- Varianten-/Response-Zählung;
- JSON-Report;
- Text-Report.

Der aktuelle HW5103-Testprofile enthält unter anderem:

- HMU B509 `/a80e`;
- HMU B509 `/ba08`;
- VWZIO B51A `/3538`;
- VWZIO B512 `/0613`.

---

## 3.4 Live-Watch

Implementiert und real validiert:

- neue Records ab aktuellem Dateiende;
- Resume von gespeichertem Offset;
- Ausgabe nur passender Evidence;
- getrennte Statistik für:
  - Frames;
  - Matches;
  - Non-Frames;
  - Skips;
  - Partial Tail;
  - Rotationen;
- ebusd-Kurzfragmente wie `<00`, `<01`, `<20` werden als `non_frames` behandelt, nicht als Parserfehler.

---

## 3.5 Persistenter Evidence-State

Implementiert und real validiert:

- Match-Zähler;
- Response-Varianten;
- Value-Varianten;
- first_seen;
- last_seen;
- Value-Status;
- kompakter JSON-State;
- atomare Writes;
- standardmäßig gebündelte Persistenz alle 5 Sekunden;
- finaler Flush beim sauberen Beenden.

---

## 3.6 Resume / Kontinuität

Implementiert:

- device;
- inode;
- Byte-Offset;
- SHA-256-Anker über die Bytes unmittelbar vor dem sicheren Offset.

Damit wird nicht nur geprüft, ob Dateisystem-ID und Offset passen, sondern auch, ob an dieser Stelle wirklich dieselbe Rawlog-Historie vorliegt.

Real validiert:

- Resume auf derselben aktiven Datei;
- Nachholen von Daten, die während einer Watch-Pause geschrieben wurden;
- Upgrade eines alten Checkpoints auf den Inhaltsanker.

Synthetisch validiert:

- eine Rename/Create-Rotation über `FILE.old`;
- verlorener/staler Checkpoint;
- Inode-Wiederverwendung;
- Content-Mismatch.

Noch offen:

- natürliche reale `ebusd.raw → ebusd.raw.old` Rotation während eines persistierten Watch-Betriebs beobachten.

---

## 3.7 Rare Context Capture

Implementiert:

- Profile können explizite Context-Trigger enthalten;
- aktuell:
  - HMU `/a80e != 0`;
  - HMU `/ba08 != 0`;
- Fenster:
  - 120 Sekunden davor;
  - 180 Sekunden danach;
- überlappende Trigger desselben Checks werden zusammengeführt;
- bestehende Bundles werden nicht überschrieben;
- Raw + JSON Sidecar;
- keine komplette Dauer-Rawlog-Kopie.

Synthetisch end-to-end validiert:

- `/ba08 = 0x20`;
- vollständiger Vorlauf;
- vollständiger Nachlauf;
- korrekter Abschlussrecord außerhalb des gespeicherten Fensters.

Noch offen:

- ein natürlicher echter Nonzero-Trigger auf einer Installation.

---

## 3.8 Share-Bundles

Implementiert und real validiert:

```bash
ebus-evidence bundle
```

Mögliche Inhalte:

- `manifest.json`;
- `profile.yaml`;
- `checksums.json`;
- bereinigter `evidence/state.json`;
- Context-Metadaten;
- optional kleine Context-Raws.

Bewusst entfernt:

- Checkpoint;
- device;
- inode;
- offset;
- anchor_start;
- anchor_sha256;
- absolute lokale Pfade;
- Host-Metadaten;
- Credentials;
- komplette Dauer-Rawlogs.

Validiert:

- zwei identische Eingaben erzeugen byte-identische ZIPs;
- alle Member haben SHA-256-Prüfsummen;
- Metadata-only Bundle ohne Raw möglich.

---

## 3.9 Bundle-Verifikation

Implementiert und real validiert:

```bash
ebus-evidence verify evidence.zip
```

Prüft:

- ZIP-Struktur;
- unsichere Pfade / Traversal;
- Duplicate Members;
- Checksummen;
- Manifest;
- Profil;
- State;
- Context-Metadaten;
- Raw-Verweise;
- verbotene lokale Resume-Felder;
- Privacy-Marker;
- kanonisches Layout.

Real validiert:

### Original

```text
Status: VALID
Deterministic layout: yes
```

### Manipuliertes Bundle

```text
INVALID: checksum mismatch for evidence/state.json
exit_code=2
```

### Inhaltlich gleiches, neu gepacktes Bundle

```text
Status: VALID
Deterministic layout: no (content integrity still valid)
```

---

# 4. Ist die README bereits Anfänger-tauglich?

## Kurzantwort

**Noch nicht vollständig.**

Sie ist für jemanden mit Linux-/Docker-Grundkenntnissen gut nachvollziehbar.

Sie ist aber noch nicht so geschrieben, dass wirklich jeder ebusd-Anfänger zuverlässig von „ich habe einen Adapter“ bis zu einem funktionierenden Evidence-Bundle kommt.

---

## 4.1 Was bereits gut ist

Die README erklärt bereits:

- Zweck und Grenzen des Projekts;
- Python-/venv-Installation;
- Docker-Rawlogging;
- native/systemd-Rawlogging;
- `doctor`;
- `analyze`;
- `watch`;
- State;
- Resume;
- Context Capture;
- Bundle;
- Verify;
- Privacy-Modell.

Das ist technisch bereits viel vollständiger als eine reine Entwickler-README.

---

## 4.2 Was einem Anfänger noch fehlt

### Voraussetzungen

Ein kompletter Anfänger weiß eventuell nicht:

- ob Python 3.11+ installiert ist;
- ob `python3-venv` fehlt;
- ob `git` installiert ist;
- wo er Befehle eingeben soll;
- was ein venv ist;
- ob er Root braucht;
- warum Dateirechte beim Rawlog relevant sind.

Dafür fehlen derzeit Copy/Paste-Prüfschritte.

### Entscheidungsbaum

Es fehlt eine frühe Frage:

> Welche Installation hast du?

Zum Beispiel:

```text
A) normales ebusd in Docker
B) normales ebusd nativ/systemd
C) normales ebusd auf einem anderen Rechner
D) micro-ebusd direkt auf dem ESP32-Adapter
E) ich weiß es nicht
```

Ohne diesen Baum liest ein Anfänger zu viele technische Optionen gleichzeitig.

### Fehlerbehebung

Es fehlen typische Fälle:

- `ebus-evidence: command not found`;
- Python zu alt;
- venv fehlt;
- Permission denied beim Rawlog;
- Docker erkannt, aber Rawlog-Mount nicht auflösbar;
- Rawlogging nicht aktiviert;
- `--lograwdata=bytes` statt Message-Mode;
- Rawlog existiert, wächst aber nicht;
- Zeitzone unbekannt;
- Profile mismatch im State;
- Resume-Gap;
- keine Context-Trigger gefunden.

---

# 5. Wichtig: Drei Ebenen dürfen nicht vermischt werden

Das ist aktuell der wichtigste Dokumentationspunkt.

## Ebene 1 — Wo läuft ebusd?

Beispiele:

- Docker;
- native/systemd;
- manuell im Terminal;
- auf einem anderen Linux-Rechner/Raspberry Pi;
- eventuell in einer Appliance/anderen Containerumgebung.

Das bestimmt, **wie wir an die Rawlog-Datei kommen**.

---

## Ebene 2 — Wie ist ebusd mit dem eBUS-Adapter verbunden?

Normales ebusd unterstützt laut Upstream unter anderem:

- serielle Verbindung / USB;
- TCP;
- UDP;
- Enhanced Protocol;
- Enhanced High Speed (`ens:`);
- Enhanced normal speed (`enh:`);
- mDNS Auto-Discovery.

Für `ebus-evidence` ist diese Ebene normalerweise **egal**.

Beispiele:

```text
ebusd in Docker
 + USB Adapter
 = für uns Docker-Rawlog

ebusd in Docker
 + ens:192.168.x.x:9999 Netzwerkadapter
 = ebenfalls Docker-Rawlog

ebusd nativ
 + mdns: Adapter Discovery
 = für uns natives Rawlog
```

Wir lesen **nicht den Adapter**.

Wir lesen das vom normalen ebusd erzeugte Message-Mode-Rawlog.

---

## Ebene 3 — Wer ist der eigentliche eBUS-Daemon?

Hier muss zwischen zwei Welten unterschieden werden:

### normales ebusd

Host-Prozess bzw. Container.

Das ist unser aktueller primärer und validierter Datenlieferant.

### micro-ebusd

micro-ebusd läuft integriert auf aktuellen ESP32-basierten Adaptern.

Es ist kein bloß anderer Netzwerktransport zu normalem ebusd, sondern kann die ebusd-artige Verarbeitung selbst auf dem Adapter übernehmen.

Das Projekt `ebusd-esp32` beschreibt micro-ebusd als integrierte Option; aktuelle Firmware bietet unter anderem eine Raw-Log-Ansicht und inzwischen auch einen Log-Download.

**Aber:**

Wir haben noch nicht validiert, ob der heruntergeladene micro-ebusd-Log exakt dem normalen ebusd Message-Mode-Rawlog entspricht.

Daher aktuell:

> micro-ebusd = noch nicht offiziell von ebus-evidence unterstützt.

Nicht raten.

Nicht einfach durch denselben Parser schicken und Support behaupten.

Zuerst reale Beispieldatei beschaffen und Format vergleichen.

---

# 6. Support-Matrix

| Setup | Status | Was ebus-evidence braucht |
|---|---|---|
| normales ebusd, Docker, USB-Adapter | **unterstützt + real validiert** | Message-Mode-Rawlog als Host-Mount |
| normales ebusd, Docker, TCP/UDP/ens/enh Netzwerkadapter | **grundsätzlich unterstützt** | derselbe Docker-Rawlog; Adaptertransport ist egal |
| normales ebusd, Docker, mDNS-Adapter | **grundsätzlich unterstützt** | derselbe Docker-Rawlog |
| normales ebusd, native/systemd, USB | **implementiert, real noch zu validieren** | lokale Rawlog-Datei |
| normales ebusd, native/systemd, Netzwerkadapter | **implementiert, real noch zu validieren** | lokale Rawlog-Datei |
| normales ebusd auf anderem Rechner | **offline unterstützt** | Rawlog kopieren oder read-only mounten und `--raw` nutzen |
| Live-Follow eines Rawlogs auf anderem Rechner ohne Mount | **noch nicht unterstützt** | späterer Remote-/Transportweg nötig |
| ebusd TCP Client Port 8888 | **kein aktueller Evidence-Eingang** | wird derzeit nicht als Raw-Stream benutzt |
| micro-ebusd | **noch nicht unterstützt** | Logformat/API zuerst real prüfen |
| ebusd byte-mode Rawlog | **bewusst nicht unterstützt** | Message-Mode verwenden |
| Windows/macOS mit kopierter Rawlog-Datei | **Offline-Analyse grundsätzlich möglich** | Python + lokale Datei |
| Home-Assistant-/Appliance-Umgebung | **abhängig von Dateizugriff** | normaler ebusd Rawlog muss erreichbar sein |

---

# 7. TCP ist nicht gleich TCP

Für Anfänger muss das ausdrücklich erklärt werden.

## TCP als Adapterverbindung

Beispiel:

```text
ebusd → TCP/ens → eBUS Adapter
```

Das ist eine **Geräteverbindung**.

Sie ändert an unserem Evidence-Workflow nichts, solange normales ebusd lokal ein Rawlog schreibt.

## TCP als ebusd Client-Port

ebusd bietet normalerweise zusätzlich einen TCP-Server für Clients wie `ebusctl`, typischerweise auf Port 8888.

Beispiel:

```text
ebusctl → TCP 8888 → ebusd
```

Das ist **nicht** dasselbe wie die Adapterverbindung.

`ebus-evidence` verwendet diesen Client-Port aktuell nicht als Haupteingang.

Das ist Absicht: Für reproduzierbare passive Analyse ist das Rawlog derzeit der stabilere gemeinsame Nenner.

---

# 8. Empfohlene Dokumentationsstruktur

Die README sollte kürzer und anfängerfreundlicher werden.

## README.md

Soll künftig nur noch enthalten:

1. Was ist ebus-evidence?
2. Ist es sicher/passiv?
3. Welche Setups werden unterstützt?
4. 5-Minuten-Quickstart.
5. Link auf ausführliche Installation.
6. Link auf Troubleshooting.
7. Link auf Community-Test.

Nicht mehr jede technische Einzelheit auf der Startseite erklären.

---

## docs/INSTALL.md

Ein echter Anfänger-Guide.

Empfohlene Struktur:

### Schritt 0 — Was hast du?

```text
[ ] ebusd in Docker
[ ] ebusd nativ/systemd
[ ] ebusd auf einem anderen Rechner
[ ] micro-ebusd
[ ] weiß ich nicht
```

### Schritt 1 — Voraussetzungen prüfen

Copy/Paste:

```bash
python3 --version
git --version
```

Debian/Ubuntu Beispiel:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

### Schritt 2 — ebus-evidence installieren

Komplett Copy/Paste.

### Schritt 3 — `doctor`

### Schritt 4 — falls Rawlogging fehlt: passenden Setup-Pfad auswählen

### Schritt 5 — `analyze`

### Schritt 6 — optional `watch`

### Schritt 7 — Bundle erstellen und prüfen.

---

## docs/EBUSD_SETUPS.md

Hierhin gehören die verschiedenen Kombinationen.

### normales ebusd / Docker

- USB Adapter;
- TCP/UDP Adapter;
- ens/enh;
- mDNS;
- Rawlog-Mount.

### normales ebusd / native systemd

- Rawlog-Optionen;
- Dateipfad;
- Dateirechte;
- Service restart;
- Logprüfung.

### normales ebusd / anderer Host

- Offline: Datei kopieren;
- besser: read-only Mount;
- kein automatisches Remote-Follow bisher.

### Nicht vermischen

- Adapterport / Netzwerkgerät;
- ebusd TCP Client-Port;
- Rawlog-Dateipfad.

---

## docs/MICRO_EBUSD.md

Zunächst Statusseite statt vorgetäuschtem Support.

Inhalt:

- Was ist micro-ebusd?
- Warum unterscheidet es sich?
- Was wissen wir bereits?
- Was muss für Support geprüft werden?
- Wie kann ein Nutzer eine Beispiel-Logdatei beisteuern?
- Welche privaten Daten vorher prüfen?

### Geplanter Prüfablauf

1. reale micro-ebusd Logdatei über offizielle Download-Funktion holen;
2. Format dokumentieren;
3. mit normalem ebusd Message-Mode vergleichen;
4. prüfen, ob bestehender Parser direkt kompatibel ist;
5. falls nein: eigener `micro-ebusd` Importer;
6. gemeinsame Normalized-Frame-Schicht beibehalten;
7. danach Doctor/Auto-Discovery nur wenn sinnvoll.

---

## docs/TROUBLESHOOTING.md

Mindestens:

- Python fehlt/zu alt;
- venv fehlt;
- Git fehlt;
- Permission denied;
- Rawlog fehlt;
- Rawlog wächst nicht;
- falscher byte mode;
- Docker mount fehlt;
- Discovery findet ebusd nicht;
- Zeitzone;
- stale checkpoint;
- profile mismatch;
- Bundle INVALID.

---

# 9. Soll ebus-evidence selbst ebusd installieren?

Aktuell: **nein**.

Das wäre eine starke Scope-Ausweitung.

ebusd hat verschiedene:

- Distributionen;
- Container-Setups;
- Adaptertypen;
- Netzwerkverbindungen;
- Config-Quellen;
- systemd-Setups.

Ein ebusd-Installer in unserem Projekt würde schnell zum eigenen Installationsprojekt werden.

Besser:

> ebus-evidence erklärt exakt, welche Rawlog-Einstellung benötigt wird und verlinkt für die eigentliche ebusd-/Adapterinstallation auf Upstream.

Später kann ein Setup-Assistent helfen, aber er sollte nicht ungefragt eine bestehende ebusd-Installation umbauen.

---

# 10. Sinnvolle nächste Features für Anfänger

## 10.1 `doctor` verbessern

Sehr hoher Nutzen.

Statt nur Fehler auszugeben, sollte `doctor` konkrete nächste Schritte nennen.

Beispiel:

```text
ebusd detected: Docker
raw logging: disabled

Next step:
Add these environment settings to your ebusd container:
  EBUSD_LOGRAWDATA=""
  EBUSD_LOGRAWDATAFILE="/rawlog/ebusd.raw"
  EBUSD_LOGRAWDATASIZE="102400"

and mount a writable host directory to /rawlog.

No change was made automatically.
```

---

## 10.2 `ebus-evidence setup` später erwägen

Nicht sofort.

Ein interaktiver Assistent könnte später nur diagnostizieren:

```text
Where does ebusd run?
1 Docker
2 native/systemd
3 another host
4 micro-ebusd
5 I don't know
```

Danach passende Anleitung ausgeben.

Wichtig:

- keine Heizungsparameter verändern;
- keine automatische Adapterkonfiguration;
- keine ungefragten ebusd-Config-Änderungen.

---

## 10.3 Installationsskript

Erst nach stabiler Dokumentation.

Mögliche spätere Form:

```bash
curl ... | ...
```

wird **nicht** empfohlen.

Besser wäre ein herunterladbares/reviewbares Script oder Paket.

Kurzfristig genügt:

```bash
git clone
python3 -m venv
pip install -e .
```

plus gute Fehlerdiagnose.

---

# 11. Priorisierte Roadmap

## P0 — Dokumentation für fremde Nutzer

**Als Nächstes.**

1. README vereinfachen.
2. `docs/INSTALL.md` schreiben.
3. `docs/EBUSD_SETUPS.md` schreiben.
4. `docs/MICRO_EBUSD.md` schreiben.
5. `docs/TROUBLESHOOTING.md` schreiben.
6. README Support-Matrix aufnehmen.

Erfolgskriterium:

> Ein Nutzer mit bestehendem normalen ebusd kann ohne Rückfrage ein gültiges State-only Evidence-Bundle erzeugen.

---

## P1 — Zweite unabhängige normale-ebusd-Installation

Danach.

Gesucht:

- möglichst andere Vaillant-/HW/SW-Konstellation;
- Docker oder native egal;
- Adaptertransport egal;
- nur Message-Mode-Rawlog nötig.

Ablauf:

```text
install
→ doctor
→ analyze
→ watch
→ bundle
→ verify
→ Ergebnisse vergleichen
```

Erfolgskriterium:

> Cross-Installation-Evidence funktioniert ohne unsere CT200-Sonderumgebung.

---

## P2 — native/systemd real validieren

Wenn die zweite Installation native ist, erledigt sich P2 automatisch.

Ansonsten gezielt einen Linux-/Raspberry-Pi-Nutzer finden.

---

## P3 — micro-ebusd Format untersuchen

Erst jetzt.

Nicht vorher Support versprechen.

Benötigt:

1. heruntergeladenes Raw-/Log-Beispiel;
2. Firmwareversion;
3. Vergleich mit normalem ebusd;
4. Entscheidung:
   - direkt kompatibel;
   - kleiner Importer;
   - API-basierter Import.

Erfolgskriterium:

> micro-ebusd-Daten können in denselben Normalized-Frame-/Evidence-Pfad überführt werden, ohne Sondersemantik in den Analysecore einzubauen.

---

## P4 — optionale read-only Metadaten

Erst wenn Cross-Installation zeigt, dass sie fehlen.

Mögliche Metadaten:

- ebusd Version;
- ebusd-configuration Revision/Quelle;
- bekannte gescannte Adressen;
- HW-/SW-Identifikatoren, sofern passiv bzw. bereits vorhanden;
- Adapter-/Verbindungsart nur grob.

Keine:

- IP-Adressen;
- Hostnamen;
- Credentials;
- Tokens.

Diese Metadaten sollten im Bundle optional und privacy-safe sein.

---

## P5 — Packaging / Betrieb

Danach:

- Docker/Compose für ebus-evidence selbst;
- systemd Unit;
- eventuell Python Package/Release;
- optional Setup-Assistent.

Erst sinnvoll, wenn die Installationswege in Dokumentation und zweiter Installation validiert sind.

---

## P6 — spätere optionale Korrelation

Noch später:

- subscribe-only MQTT-Kontext;
- keine MQTT-Pflicht;
- kein Publish;
- Evidence weiterhin rawlog-basiert.

---

# 12. Was wir jetzt ausdrücklich nicht machen sollten

Nicht jetzt:

- eigene ebusd-Installation automatisieren;
- direkten Adapterzugriff hinzufügen;
- TCP-Port 8888 zum primären Evidence-Transport machen;
- micro-ebusd ohne reales Logformat als unterstützt deklarieren;
- große Web-UI bauen;
- Analyzer-Datenbank nachbauen;
- MQTT verpflichtend machen;
- automatische Bedeutungsnamen erzeugen;
- unbekannte Register aktiv pollen;
- zehn weitere Profile hinzufügen, bevor eine zweite Installation den Workflow getestet hat.

---

# 13. Konkrete nächste Arbeitsreihenfolge

Empfohlene Reihenfolge ab jetzt:

```text
1. Anfänger-README / INSTALL-Dokumentation
        ↓
2. ebusd-Setup-Matrix USB/TCP/UDP/mDNS + Docker/native
        ↓
3. Troubleshooting
        ↓
4. zweite normale-ebusd-Installation
        ↓
5. daraus echte Bedienprobleme beheben
        ↓
6. native/systemd real abhaken
        ↓
7. micro-ebusd Beispiel beschaffen und Format prüfen
        ↓
8. erst dann über micro-ebusd Importer / read-only Metadaten entscheiden
```

---

# 14. Einschätzung README heute

Grobe Bewertung für das derzeitige Ziel:

| Bereich | Stand |
|---|---|
| Technische Projektbeschreibung | sehr gut |
| Sicherheits-/Read-only-Erklärung | sehr gut |
| Nutzung nach erfolgreicher Installation | gut bis sehr gut |
| Docker Rawlogging | gut |
| native Rawlogging | brauchbar |
| Anfänger ohne Linux-Erfahrung | noch zu anspruchsvoll |
| Auswahl des richtigen Installationswegs | unzureichend |
| USB vs TCP vs UDP vs mDNS Erklärung | fehlt als klares Modell |
| Remote-ebusd Erklärung | fehlt |
| micro-ebusd Abgrenzung | fehlt |
| Troubleshooting | noch zu dünn |
| Copy/Paste-Erstinstallation | noch nicht vollständig genug |

**Fazit:**

Die README ist technisch gut, aber noch keine „jeder bekommt es installiert“-Anleitung.

Das ist jetzt der wichtigste Produkt-/Community-Schritt.

---

# 15. Upstream-Fakten, auf denen die Setup-Matrix basiert

Normales ebusd unterstützt laut aktueller Upstream-Dokumentation unter anderem:

- serial/USB;
- TCP;
- UDP;
- enhanced Protocol;
- `ens:`;
- `enh:`;
- mDNS Discovery.

Der ebusd TCP-Client-Port für `ebusctl` ist davon getrennt und liegt üblicherweise auf Port 8888.

Aktuelle empfohlene Adapterfamilien umfassen unter anderem C6, v5 und Adapter 3.x mit USB/Raspberry-Pi/Wi-Fi/Ethernet-Verbindungen.

micro-ebusd ist inzwischen Bestandteil der ESP32-Firmwarefamilie und bietet unter anderem integrierte Message-Verarbeitung, MQTT/Home-Assistant-Funktionen, Raw-Log-Ansicht und Log-Download. Das ist technisch ein eigener Datenlieferant und muss vor offiziellem `ebus-evidence`-Support separat validiert werden.

Upstream-Referenzen:

- https://github.com/john30/ebusd
- https://github.com/john30/ebusd/wiki
- https://github.com/john30/ebusd/wiki/2.-Run
- https://github.com/john30/ebusd/wiki/5.-Tools
- https://github.com/john30/ebusd/wiki/6.-Hardware
- https://github.com/john30/ebusd-esp32
- https://github.com/john30/ebusd-esp32/blob/main/CHANGELOG.md

---

# 16. Ziel für den nächsten dokumentierten Meilenstein

Der nächste Meilenstein sollte nicht „mehr Decoder“ heißen.

Er sollte heißen:

> **A new user can install ebus-evidence, identify the correct normal-ebusd setup, enable/locate a Message-Mode-Rawlog, run doctor/analyze/watch, and create+verify a shareable evidence bundle without project-specific help.**

Danach ist das Projekt bereit für einen echten Community-/Cross-Installation-Test.
