<p align="center">
  <img src="resources/app.png" alt="AnkAlt Launcher Logo" width="120" />
</p>

<h1 align="center">AnkAlt Launcher</h1>

<p align="center">
  A tool that emulates the Launcher to launch <b>D3</b> and <b>DRETRO</b> directly — without needing the official launcher.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/Valentin-alix/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/downloads/Valentin-alix/AnkamaLauncherEmulator/total?style=for-the-badge" />
  <img src="https://img.shields.io/github/stars/Valentin-alix/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/issues/Valentin-alix/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/github/license/Valentin-alix/AnkamaLauncherEmulator?style=for-the-badge" />
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=for-the-badge" />
</p>

---

![Screenshot](docs/screenshot.png)

## How to use it

Simply get the `.exe` in Releases and execute it.

> **Note:** Install `cytrus-v6` to enable automatic game updates before each launch:
> ```bash
> npm install -g cytrus-v6
> ```
> Without it, the tool still works but won't auto-update your game files.

Then you access this beautiful (no) interface

---

## How it works

The official Launcher stores your credentials encrypted in `%APPDATA%\zaap\`. This tool:

1. Reads and decrypts those stored API keys using your machine's UUID
2. Starts a local Thrift server on port `26116` (the same port the game expects from the launcher)
3. Intercepts the game's connection via a transparent proxy (mitmproxy)
4. Optionally checks for game updates via `cytrus-v6` before launching
5. Launches `Dofus.exe` with the correct arguments so it connects to the local emulated launcher instead of Zaap

You must have logged in at least once through the official Ankama Launcher so that your credentials are stored locally.

### Additional features
- Add new account via alternative launcher
- Per account HWID
- Multi-account support with per-account proxy and network interface

---

## Requirements

- **D3** or **DRETRO** installed via the official Ankama Launcher (at least one account logged in)
- **Python >= 3.12**
- **uv** — fast Python package manager
- **cytrus-v6** *(optional)* — enables automatic game updates at launch time

Install uv:

```bash
pip install uv