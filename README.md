# clipt

[![PyPI version](https://img.shields.io/pypi/v/clipt.svg?color=blue)](https://pypi.org/project/clipt/)
[![Python versions](https://img.shields.io/pypi/pyversions/clipt.svg)](https://pypi.org/project/clipt/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/xibhi/clipt/blob/master/LICENSE)

A terminal clipboard manager. Copies text, files, or command output to the clipboard, keeps a local SQLite history, and lets you pin, search, share, or delete entries from the command line.

## Features

- Copies text, file contents, or stdin to the clipboard
- Runs a shell command, streams its output live, copies the result (`ocopy`)
- Stores every copy in a local SQLite history with a source tag
- Assigns each entry a random 10-digit ID plus a running index
- Recalls a past entry back to the clipboard without touching history
- Full-text search across history (`grep`)
- Pin/unpin entries by index or ID to exclude them from `clear`
- Uploads text, a history entry, or command output to paste.rs, returns a link
- Deletes all unpinned entries (`clear`) or truly everything (`kaboom`)
- Deletes one specific entry by index or ID (`kill`)
- Shows aggregate stats — total count, pinned count, per-source breakdown
- Interactive config editor, plus `list`/`get`/`set`/`reset`/`path` for scripting (`--config`)
- Self-installs onto system PATH on POSIX and Windows (`--init`)
- Fully removes itself, its data, and PATH edits (`--uninstall`)

## Installation

Prerequisites: Python `>=3.10`, pip.

```bash
git clone https://github.com/xibhi/clipt.git
cd clipt
```

Then set up a virtual environment:

```bash
# Windows (PowerShell)
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

```

Then install:

```bash
pip install .        # standard
pip install -e .     # editable, for development
```

Then register it on your PATH:

```bash
clipt --init
```

On Windows, this writes `clipt.cmd`/`clipt.ps1` to `~/.local/bin`, adds that directory to your User PATH via the registry, and updates your PowerShell profile. On Linux/macOS, it tries `/usr/local/bin` or `/usr/bin` first if you're on a system Python; if neither is writable (the common case when installed inside a venv, as above), it falls back to `~/.local/bin` and adds it to `.bashrc`, `.zshrc`, and the fish config.

## Quick Start

```bash
clipt --init                # register clipt on your PATH
clipt copy "hello"           # copies "hello", saves it to history
clipt history                # lists everything you've copied
clipt pin 1                  # pin entry 1 so `clear` won't touch it
```

## Commands

| Command | Description |
|---|---|
| `clipt --version` | Show the version and exit |
| `clipt --config` | View or change configuration settings |
| `clipt --help` | Show this message |
| `clipt --init` | Configure system PATH to use clipt anywhere |
| `clipt --uninstall` | Completely remove clipt and all its data from the system |
| `clipt copy` | Copy text to the clipboard |
| `clipt copy --file` | Copy text from a file |
| `clipt ocopy` | Run any terminal command, stream its output, and copy the result |
| `clipt recall` | Copy a past history entry to clipboard by index or ID |
| `clipt history` | View saved clipboard history |
| `clipt grep` | Search clipboard history for a string |
| `clipt pin` | Pin an entry to prevent deletion during clear |
| `clipt unpin` | Unpin an entry |
| `clipt pins` | View all pinned entries |
| `clipt share` | Upload text to paste.rs and return a link |
| `clipt clear` | Delete all history entries except pinned items |
| `clipt kaboom` | Delete all history entries including pinned items |
| `clipt kill` | Delete a single entry from history |
| `clipt stats` | Show usage statistics |

Tip: wrap text in double quotes (`"..."`) if it contains symbols like `<`, `>`, `|`, `&`, `\$`, or `;`.

## Configuration

- Config file: `~/.config/clipt/config.toml`, auto-created on first run
- `max_history_entries` (default `500`), `auto_save_history` (default `true`), `deduplicate_consecutive` (default `true`), `share_service` (locked to `paste.rs` — the only supported backend right now)
- History: `~/.local/share/clipt/history.db` (SQLite)
- Both files are created with `0o600` permissions
- No environment variables
- Edit settings via `clipt --config`:

```bash
clipt --config                          # interactive settings editor
clipt --config list                     # view settings in a static table
clipt --config <setting>                # view a setting's current value
clipt --config <setting> <value>        # update a setting
clipt --config set <setting> <value>    # update a setting, explicitly
clipt --config get <setting>            # get a setting, explicitly
clipt --config reset                    # restore defaults
clipt --config path                     # show the config file path
```

## Architecture

```bash
clipt/
├── .clipt-messages/
│   ├── error.txt              # cycling error-message templates
│   └── success.txt            # cycling success-message templates
├── __init__.py                 # version string, Rich alignment patch
├── __main__.py
├── config.py                   # config.toml load/save, defaults
├── db.py                        # SQLite schema, history CRUD
├── hooks.py                      # --init / --uninstall, PATH + shell rc edits
├── LICENSE
├── main.py                        # Typer CLI commands
├── message_manager.py              # cycling success/error message resolution
├── pyproject.toml
├── README.md
└── utils.py                         # clipboard I/O, output formatting
```

A couple of decisions worth a one-liner each:

- `share`'s piped-input confirmation reads from `/dev/tty`/`CONIN\$` directly, since stdin is already consumed by the pipe by the time the prompt would run
- The messages directory is resolved by checking three candidate paths in order, to handle editable-install, normal-install, and fallback layouts

## How clipt Works

clipt stores everything locally.

- **History** is written to `~/.local/share/clipt/history.db` (SQLite) every time `copy`, `ocopy`, or `share` runs — each row gets a random 10-digit ID, a running index, and a source tag.
- **Pinned entries** are flagged in the database and excluded from `clear` (`kaboom` ignores the flag and deletes everything).
- **Config** lives at `~/.config/clipt/config.toml`, auto-created with defaults on first run.
- **`ocopy`'s output capture** doesn't rely on a sourced shell hook — it runs your command as a subprocess directly, streaming stdout to your terminal live while capturing the same output for the clipboard, in one step.
- **`clipt --init`** registers clipt on your PATH (see Installation for the exact OS-specific behavior) — no separate hook-sourcing step required afterward.

## ocopy

`ocopy` is clipt's signature command — run anything, get its output on your clipboard, without breaking your terminal's live view of what's happening.

Raw args after `ocopy` are pulled straight from argv → the command runs as a list-form subprocess → its stdout streams live to your terminal while being captured in the same pass → the captured output is written to the clipboard → a parameterized INSERT adds it to history with a generated 10-digit ID and the `ocopy` source tag → a cycling success message prints.

Subprocess args are passed as a list, not a joined string, so already-resolved argument text isn't re-interpreted as shell syntax.

## FAQs

**Q. Where does my clipboard history actually live?**

A. `~/.local/share/clipt/history.db`, a local SQLite file with `0o600` permissions — nothing leaves your machine except what you explicitly `share`.

**Q. What happens when I run `clear`?**

A. Every unpinned entry is deleted. Pinned entries survive. `kaboom` deletes everything, pinned or not.

**Q. Can I change where entries get shared to?**

A. Not yet — `share_service` in `config.toml` is reset to `paste.rs` if you set it to anything else. One backend is supported right now.

**Q. Does `ocopy` capture output as it runs, or only at the end?**

A. It streams live to your terminal while capturing the same output for the clipboard — you see it as it happens, not just after the command finishes.

## License

This project is licensed under the [MIT License](LICENSE).
