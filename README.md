<p align="center">
  <img src="resources/app.png" alt="AnkAlt Launcher Logo" width="120" />
</p>

<h1 align="center">AnkAlt Launcher</h1>

<p align="center">
  A tool that emulates the Launcher to launch <b>D3</b> and <b>DRETRO</b> directly — without needing the official launcher.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/tagius/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/downloads/tagius/AnkamaLauncherEmulator/total?style=for-the-badge" />
  <img src="https://img.shields.io/github/stars/tagius/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/issues/tagius/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/license/tagius/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge" />
</p>

---

![Screenshot](docs/screenshot.png)

## Download (recommended)

No build required. Grab the ready-made Windows binary:

1. Go to [**Releases**](https://github.com/Valentin-alix/AnkamaLauncherEmulator/releases)
2. Download the latest `AnkAlt Launcher.exe` under **Assets**
3. Run it

> **First run:** The launcher can auto-install `cytrus-v6` for game updates. If you skip it, you can still launch games but updates will not be automatic.

---

## How it works

The official launcher stores your credentials encrypted in `%APPDATA%\zaap\`. This tool:

1. Reads and decrypts those stored API keys using your machine's UUID
2. Starts a local Thrift server on port `26116` (the same port the game expects from the launcher)
3. Intercepts the game's connection via a transparent proxy (mitmproxy)
4. Optionally checks for game updates via `cytrus-v6` before launching
5. Launches `Dofus.exe` with the correct arguments so it connects to the local emulated launcher instead of Zaap

You must have logged in at least once through the official Ankama Launcher so that your credentials are stored locally.

---

## Features

- **Multi-account** support with per-account proxy and network interface
- **Per-account HWID**
- **Portable account import/export** — encrypt and share account bundles with a passphrase
- **Built-in update checker** — notifies you when a new release is available on GitHub
- **Settings & diagnostics** — debug mode toggle, log folder access, one-click diagnostics copy
- **Shield recovery** and WAF bypass for auth flows
- **Game tab memory** — remembers your last selected game between sessions

---

## Requirements

- **Windows** (credential decryption and game launch are Windows-only)
- **D3** or **DRETRO** installed via the official Ankama Launcher (at least one account logged in)
- **Python >= 3.12** *(only for running from source)*
- **uv** *(only for running from source)* — fast Python package manager

---

## Build from source

### Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- (Optional) [Apache Thrift](https://thrift.apache.org/docs/install/) — only if you modify `resources/zaap.thrift`
- (Optional) [Node.js + npm](https://nodejs.org/) — only if you want to install `cytrus-v6` manually instead of using the built-in installer

### Clone and run

```bash
git clone https://github.com/Valentin-alix/AnkamaLauncherEmulator
cd AnkamaLauncherEmulator
uv sync
uv run main.py
```

### Build the executable

```bash
uv run pyinstaller main.spec
```

Output goes to `dist/AnkAlt Launcher.exe`.

A GitHub Action also builds this automatically on every push to `master` (see `.github/workflows/build-windows.yml`).

### Development commands

```bash
# Run tests
uv run python -m pytest tests/

# Typecheck
uv run pyright

# Format code
uv run black .

# Regenerate Thrift bindings (only when zaap.thrift changes)
thrift --gen py resources/zaap.thrift && mv gen-py ankama_launcher_emulator/gen_zaap
```

### Inspect the Ankama Launcher source

To explore the launcher's internals, extract the `app.asar` bundle:

```bash
asar extract "C:/Program Files/Ankama/Ankama Launcher/resources/app.asar" "<output_dir>"
```

---

## Troubleshooting

- Enable **Debug Mode** in the settings dialog to write verbose logs to `%APPDATA%\AnkamaLauncherEmulator\ankalt_debug.log`.
- Use **Copy Diagnostics** in settings to gather system info for bug reports.
- If login fails with a WAF or shield loop, the tool will retry automatically; persistent failures are logged in debug mode.

---

## License

[MIT](LICENSE)
