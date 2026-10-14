# Xyrus update: safety, reliability, honesty, new tools, new dashboard

Copy the files in this archive over the same paths in your project. Your
`config/`, `memory/` and `.venv` are not in the archive and are not touched.
Back up first if you like; to roll back, copy your old files back.
Nothing needs installing: every change uses what is already in requirements.txt.

## 1. Safety

| What | Where |
|---|---|
| **Confirm before acting for you.** `send_message`, `code_helper` (run/build), `dev_agent` and `desktop_control` scripts now wait for the on-screen CONFIRM button (the same gate shutdown already used). Switch: **Controls, "Confirm risky actions"** (default on), or per tool via `tool_policies` in `config/api_keys.json` (`ask` / `allow` / `deny`). | `core/permissions.py` (new), the four actions, `memory/config_manager.py` |
| **Scripts the model writes are read before they run.** No imports, no `getattr`/`eval`/`open`, no `__dunder__` access, no delete/overwrite calls, no `ctypes`. The confirmation shows you the script. | `actions/desktop.py` |
| **Command injection in `open_app` (Windows)** removed: app names are checked and never go through a shell. | `actions/open_app.py` |
| **`pip` option smuggling** in `dev_agent`: only plain package names are installed. | `actions/dev_agent.py` |
| **Dashboard**: 5 wrong pairing tries lock an address out for 5 minutes; auth tokens expire after 12 hours (and no longer pile up). | `dashboard/security.py` (new), `dashboard/server.py` |
| **Audit log** of every tool call (secrets redacted) in `memory/audit.log`. | `core/permissions.py`, `main.py` |

## 2. Reliability

* **Tools can no longer freeze the voice session.** Each tool has a time limit (`core/permissions.py: TOOL_TIMEOUTS`); on timeout the model is told so and must not claim success. (`main.py`)
* `dev_agent` could not open VS Code on macOS/Linux (a list combined with `shell=True`); it also reported success when VS Code was missing. Fixed.
* **154 silent `except Exception: pass`** now write one line to `memory/debug.log` (repeats collapsed, size-capped) and behave exactly as before otherwise. (`core/diag.py`)
* Network speed in System Status uses the real elapsed time, not an assumed 1.5 s.
* `ui.py` crashed on a video error (`self.write_log` did not exist); fixed in `ui_new.py`.

## 3. Honesty (the model is told what is true)

* Parameters the code read but the model was never told about are now declared: `browser_control.fields`, `file_controller.append/max_results`, `weather_report.time`, `computer_settings.press_enter`. `browser_control.incognito` was declared but never implemented, so it was removed.
* The system prompt now explains confirmations, timeouts, `search_history` and reminder list/cancel.

## 4. New abilities

* **Reminders: list and cancel.** `reminder` takes `action=list|cancel`. Set reminders are recorded in `~/.jarvis/reminders/index.json`. (Reminders set before this update are not in the list; they still fire.) The dashboard's Reminders panel shows the real list.
* **Conversation history and search.** Every turn is kept in `memory/history.jsonl`; the new `search_history` tool answers "what did I ask you about the invoice yesterday?".
* **macOS GPU and thermal state** without root (`ioreg`, `pmset`). A Mac does not give degrees without root, so TEMP shows OK / Warm / Hot.
* **The avatar is drawn again.** `HoloAvatar.paint()` existed but nothing called it. HUD style "face" or "cartoon" now draws the head; any failure falls back to the reactor.

## 5. New interface (`ui_new.py`)

The dashboard from your design. `main.py` now imports `ui_new`. `ui.py` is untouched; the previous two versions are `ui_console_v2.py` and `ui_restyle.py`.

## 6. Cleanup

* `main.py` no longer imports five unused `app/` classes (one of them a stub that the real `JarvisLive` silently shadowed). The `app/` files themselves are left alone.

## 7. Tests

`tests/test_hardening.py`: 36 tests (permissions, sandbox, open_app filter, dev_agent, history, reminders, dashboard limiter and tokens, macOS parsers, diagnostics, and repo-wide guards such as "no `shell=True` with a multi-item list"). Run: `python -m pytest tests/test_hardening.py`.

## Deliberately not done

* Calendar, email and smart-home need OAuth keys or device keys and cannot be tested without them; requirements.txt already lists the extras for the community plugins that provide them.
* Offline voice (`core/tts.py`, `core/stt.py` exist but are not wired), voice barge-in, document search, auto-update, installers: each needs models or an audio pipeline I cannot exercise here.
* Dashboard AES key derivation: changing it needs the browser script changed in step; TLS protects the link today.
* Face and voice recognition are simple matchers; do not use them as a security lock.
* `game_updater` stays Windows-only.
