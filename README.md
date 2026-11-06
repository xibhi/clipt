# clipt

**clipt** is a terminal clipboard manager. Copies text, files, or command output to the clipboard, keeps a local SQLite history, and lets you pin, search, share, or delete entries from the command line.

---

## Features

- **Live stream capture (`ocopy`)** — Executes commands as a child subprocess, streaming stdout live to your terminal while duplexing identical output directly to your clipboard.
- **Persistent SQLite history** — Records every clip with timestamps, source tags, running indexes, and unique 10-digit IDs under strict `0600` permissions.
- **Full-text search** — Queries entire clipboard history instantly with `grep` substring matching.
- **Pinning & cleanup** — Protect critical tokens, SSH keys, and commands from routine deletion with `pin`; wipe unpinned clutter with `clear` or purge everything with `kaboom`.
- **Zero-friction sharing** — Direct pipe-to-web sharing via paste.rs with interactive confirmation prompts.

---

## Install

```bash
git clone https://github.com/xibhi/clipt.git
cd clipt
pip install .
clipt --init # configures PATH automatically
```

---

## Commands

| Command | Action |
| :--- | :--- |
| `clipt copy "<text>"` | Copy text to clipboard and history |
| `clipt copy --file <path>` | Copy entire file contents to clipboard |
| `clipt ocopy <command>` | Run command, stream output live, and copy result |
| `clipt history` | Display indexed clipboard history |
| `clipt recall <id/index>` | Yank past entry back into clipboard without modifying history |
| `clipt grep "<pattern>"` | Search history for matching text |
| `clipt pin <id/index>` | Pin entry to protect it from `clear` |
| `clipt unpin <id/index>` | Remove pinned status |
| `clipt pins` | View all pinned entries |
| `clipt share` | Upload clipboard or stdin to paste.rs and return URL |
| `clipt clear` | Delete all unpinned history entries |
| `clipt kaboom` | Delete entire history including pinned entries |
| `clipt kill <id/index>` | Delete a single history entry |
| `clipt stats` | Show total entries, pinned count, and source breakdown |
| `clipt --config` | Launch interactive configuration editor |

---

## FAQ

**Where is clipboard history stored?**  
In `~/.local/share/clipt/history.db` (SQLite) with `0600` permissions. No background daemon or socket server required.

**How does `ocopy` capture output without breaking the terminal?**  
It launches the target command as a subprocess with unbuffered stdout streaming, printing to your terminal in real time while capturing the byte stream for clipboard memory.

**What is the difference between `clear` and `kaboom`?**  
`clear` purges standard clipboard history while preserving all items tagged with `pin`. `kaboom` unconditionally flushes the entire database.

**Does clipt send data over the network?**  
Only when explicitly running `clipt share`, which uploads text to paste.rs after an interactive confirmation prompt on `/dev/tty`.

**How do I adjust history limits?**  
Run `clipt --config` to edit `max_history_entries` (default `500`) and deduplication rules in `~/.config/clipt/config.toml`.

---

## License

This project is licensed under the [MIT License](LICENSE).
