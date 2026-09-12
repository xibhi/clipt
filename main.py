from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, TextIO

import typer
try:
    import typer.rich_utils as typer_rich_utils

    typer_rich_utils.ALIGN_ERRORS_PANEL = "center"
    typer_rich_utils.ALIGN_COMMANDS_PANEL = "center"
    typer_rich_utils.ALIGN_OPTIONS_PANEL = "center"
except Exception:
    pass
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

try:
    from . import __version__
    from .config import (
        CONFIG_METADATA,
        CONFIG_PATH,
        DEFAULT_CONFIG,
        Config,
        load_config,
        reset_config,
        set_config_value,
    )
    from .db import (
        HistoryEntry,
        add_history,
        count_history,
        delete_history_entry,
        get_entry_by_index,
        get_entry_by_item_id,
        latest_entry,
        list_history,
        search_history,
        set_pinned,
        stats as db_stats,
        wipe_all,
        wipe_unpinned,
    )
    from .hooks import install_clipt, uninstall_clipt
    from .utils import (
        CliptError,
        console,
        preview,
        print_error,
        print_info,
        print_success,
        print_warning,
        read_clipboard,
        read_text_file,
        share_text,
        strip_ansi,
        top_words,
        write_clipboard,
    )
except ImportError:
    try:
        from __init__ import __version__
    except ImportError:
        __version__ = "1.0.0"
    from config import (
        CONFIG_METADATA,
        CONFIG_PATH,
        DEFAULT_CONFIG,
        Config,
        load_config,
        reset_config,
        set_config_value,
    )
    from db import (
        HistoryEntry,
        add_history,
        count_history,
        delete_history_entry,
        get_entry_by_index,
        get_entry_by_item_id,
        latest_entry,
        list_history,
        search_history,
        set_pinned,
        stats as db_stats,
        wipe_all,
        wipe_unpinned,
    )
    from hooks import install_clipt, uninstall_clipt
    from utils import (
        CliptError,
        console,
        preview,
        print_error,
        print_info,
        print_success,
        print_warning,
        read_clipboard,
        read_text_file,
        share_text,
        strip_ansi,
        top_words,
        write_clipboard,
    )


class _TerminalStream:
    """Wrapper around a terminal input stream to strip trailing newlines for Rich's Confirm.ask."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def readline(self, *args: Any, **kwargs: Any) -> str:
        line = self._stream.readline(*args, **kwargs)
        return line.rstrip("\r\n") if line else ""

    def read(self, *args: Any, **kwargs: Any) -> str:
        return self._stream.read(*args, **kwargs)

    def close(self) -> None:
        self._stream.close()


app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": []},
    no_args_is_help=False,
    rich_markup_mode="rich",
)

WEEKDAYS = {
    "0": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
}


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    load_config()
    if ctx.invoked_subcommand is None:
        show_help()
        raise typer.Exit()


def _save_if_enabled(content: str, source: str) -> None:
    cfg = load_config()
    if cfg.auto_save_history:
        add_history(
            content,
            source,
            max_entries=cfg.max_history_entries,
            deduplicate_consecutive=cfg.deduplicate_consecutive,
        )


def _run(action) -> None:
    try:
        action()
    except (typer.Exit, SystemExit):
        raise
    except CliptError as exc:
        print_error(str(exc), command=exc.command, replacements=exc.replacements)
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        print_warning("Interrupted.")
        raise typer.Exit(130) from None
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        try:
            home = Path.home()
            for h in (str(home), home.as_posix(), str(home).replace("\\", "\\\\")):
                if h and h in msg:
                    msg = msg.replace(h, "~")
                if h and h.lower() in msg.lower():
                    # Case-insensitive path replacement for Windows
                    lower_msg = msg.lower()
                    lower_h = h.lower()
                    idx = lower_msg.find(lower_h)
                    while idx != -1:
                        msg = msg[:idx] + "~" + msg[idx + len(h):]
                        lower_msg = msg.lower()
                        idx = lower_msg.find(lower_h, idx + 1)
        except Exception:
            pass
        print_error(msg)
        raise typer.Exit(1) from exc


def _history_table(entries: list[HistoryEntry], *, title: str = "Clipboard History", enumerate_from_latest: bool = True) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("Index", style="bold", justify="right")
    table.add_column("Item", overflow="fold")
    table.add_column("ID", style="magenta")
    table.add_column("Created On", style="dim")
    all_entries = list_history()
    index_by_id = {entry.id: idx for idx, entry in enumerate(all_entries, start=1)}

    enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    try:
        "⭐".encode(enc)
        star_icon = "⭐ "
    except Exception:
        star_icon = "* "

    for local_idx, entry in enumerate(entries, start=1):
        idx = index_by_id.get(entry.id, local_idx) if enumerate_from_latest else local_idx
        pin = star_icon if entry.pinned else ""
        table.add_row(
            str(idx),
            pin + preview(entry.content, 60),
            entry.item_id,
            entry.created_on,
        )
    return table


def _try_resolve_entry(target: str) -> tuple[int, HistoryEntry] | None:
    if target.isdigit() and len(target) == 10:
        return get_entry_by_item_id(target)
    if target.isdigit():
        return get_entry_by_index(int(target))
    return None


def _resolve_entry_or_error(target: str, command: str) -> tuple[int, HistoryEntry]:
    if target.isdigit() and len(target) == 10:
        result = get_entry_by_item_id(target)
        if result is None:
            raise CliptError(f"No entry found with ID '{target}'.", command=command, replacements={"id": target})
        return result
    if target.isdigit():
        idx = int(target)
        result = get_entry_by_index(idx)
        if result is None:
            total = count_history()
            raise CliptError(
                f"Index out of range. Valid range: 1-{total}.",
                command=command,
                replacements={"n": idx, "max": total},
            )
        return result
    raise CliptError("Enter a valid index or 10-digit ID.")


def _extract_raw_command_args(token: str, ctx: Optional[typer.Context] = None) -> list[str]:
    if ctx is not None and ctx.args:
        return list(ctx.args)
    for idx, arg in enumerate(sys.argv):
        if arg == token:
            return sys.argv[idx + 1 :]
    return []


def _run_and_tee_subprocess(cmd_args: list[str]) -> tuple[int, str]:
    if not cmd_args:
        return 0, ""
    if platform.system() == "Windows":
        ps_exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        # Run via PowerShell on Windows so shell aliases (ls, cat, curl, pwd) and cmdlets work,
        # but quote and splat arguments strictly to prevent subexpression or metacharacter evaluation.
        def _ps_quote(s: str) -> str:
            return "'" + s.replace("'", "''") + "'"

        c_str = _ps_quote(cmd_args[0])
        quoted_args = ", ".join(_ps_quote(arg) for arg in cmd_args[1:])
        script = (
            f"$c = {c_str}; $a = @({quoted_args}); & $c @a; "
            f"if ($LASTEXITCODE -ne $null) {{ exit $LASTEXITCODE }} elseif (-not $?) {{ exit 1 }} else {{ exit 0 }}"
        )
        popen_args = [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]
        shell_flag = False
        executable = None
    else:
        popen_args = cmd_args
        shell_flag = False
        executable = None

    captured: list[str] = []
    proc = subprocess.Popen(
        popen_args,
        shell=shell_flag,
        executable=executable,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
    proc.wait()
    raw_output = "".join(captured)
    clean_output = strip_ansi(raw_output)
    return proc.returncode, clean_output


def show_help() -> None:
    console.print("Usage: clipt [OPTIONS] COMMAND [ARGS]...")
    console.print()
    console.print("      Command-line clipboard manager.")
    console.print()
    console.print("Options:")
    console.print("  --version    Show the version and exit.")
    console.print("  --config     View or change configuration settings.")
    console.print("  --help       Show this message.")
    console.print("  --init       Configure system PATH to use clipt anywhere.")
    console.print("  --uninstall  Completely remove clipt and all its data from the system.")
    console.print()
    console.print("Commands:")

    commands = [
        ("copy", "Copy text to the clipboard."),
        ("  --file", "Copy text from a file."),
        ("ocopy", "Run any terminal command, stream its output, and copy the result."),
        ("recall", "Copy a past history entry to clipboard by index or ID."),
        ("history", "View saved clipboard history."),
        ("grep", "Search clipboard history for a string."),
        ("pin", "Pin an entry to prevent deletion during clear."),
        ("unpin", "Unpin an entry."),
        ("pins", "View all pinned entries."),
        ("share", "Upload text to paste.rs and return a link."),
        ("clear", "Delete all history entries except pinned items."),
        ("kaboom", "Delete all history entries including pinned items."),
        ("kill", "Delete a single entry from history."),
        ("stats", "Show usage statistics."),
    ]

    for cmd, desc in commands:
        text = Text(f"  {cmd:<18} {desc}", no_wrap=False)
        console.print(text)
    console.print()
    console.print("  [dim]Tip: Wrap text in double quotes (\"...\") if it contains symbols like <, >, |, &, $, or ;[/dim]")
    console.print()


@app.command("help")
def help_command() -> None:
    show_help()


@app.command("copy")
def copy_command(
    text: Optional[list[str]] = typer.Argument(None),
    file_path: Optional[Path] = typer.Option(
        None,
        "--file",
        metavar="PATH",
        help="Copy text from a file.",
    ),
) -> None:
    def action() -> None:
        if file_path is not None:
            content = read_text_file(file_path)
            source = "file"
        elif text:
            content = " ".join(text)
            source = "manual"
        elif not sys.stdin.isatty():
            content = sys.stdin.read()
            source = "pipe"
        else:
            raise CliptError(
                'No input provided. Provide text in quotes: clipt copy "your text"\nTip: Wrap in double quotes if your text contains shell characters (<, >, |, &, $, ;).',
                command="copy no input given",
            )
        write_clipboard(content)
        _save_if_enabled(content, source)
        default_msg = f'Copied {len(content)} characters to clipboard.'
        cmd_name = "copy --file" if file_path is not None else "copy"
        print_success(
            default_msg,
            command=cmd_name,
            replacements={"n": len(content), "path": str(file_path or "")},
        )

    _run(action)


@app.command("ocopy", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def ocopy_command(ctx: typer.Context) -> None:
    """Run any terminal command, stream its output, and copy the result."""
    raw_args = _extract_raw_command_args("ocopy", ctx)
    if not raw_args:
        print_warning("No command provided. Usage: clipt ocopy <command...>")
        return

    def action() -> None:
        exit_code, output = _run_and_tee_subprocess(raw_args)
        if not output:
            print_warning("Command produced no output.")
        else:
            write_clipboard(output)
            _save_if_enabled(output, "ocopy")
            console.print(f"[bold green]Copied command output[/] ({len(output)} chars)")
            console.print(f'Preview: "{preview(output)}"')
        if exit_code != 0:
            raise typer.Exit(exit_code)

    _run(action)


@app.command("recall")
def recall_command(target: Optional[str] = typer.Argument(None, help="Index or 10-digit ID")) -> None:
    """Copy a past history entry to clipboard by index or ID without altering history."""
    def action() -> None:
        if not target:
            raise CliptError("Provide an index or 10-digit ID to recall: clipt recall <index|id>", command="recall no input")
        idx, entry = _resolve_entry_or_error(target, command="recall index out of range")
        write_clipboard(entry.content)
        default_msg = f"Recalled entry {idx} (ID: {entry.item_id}) to clipboard."
        print_success(
            default_msg,
            command="recall",
            replacements={"n": idx, "id": entry.item_id},
        )

    _run(action)


@app.command("history")
def history_command(
    limit: int = typer.Option(20, "--limit", min=1, help="Number of entries to show.")
) -> None:
    def action() -> None:
        entries = list_history(limit)
        if not entries:
            print_info("Clipboard history is empty.", command="history empty")
            return
        console.print(_history_table(entries))

    _run(action)


@app.command("grep")
def grep_command(query: Optional[str] = typer.Argument(None, help="Search query")) -> None:
    def action() -> None:
        if not query:
            raise CliptError("Provide a search query: clipt grep <query>", command="grep no input")
        entries = search_history(query)
        if not entries:
            print_warning(f'No history entries matched "{query}".')
            return
        console.print(_history_table(entries, title=f'Search Results for "{query}"'))

    _run(action)


@app.command("pin")
def pin_command(target: Optional[str] = typer.Argument(None, help="Index or 10-digit ID")) -> None:
    def action() -> None:
        if not target:
            raise CliptError("Provide an index or 10-digit ID to pin: clipt pin <index|id>", command="pin no input")
        idx, entry = _resolve_entry_or_error(target, command="pin index out of range")
        if entry.pinned:
            print_info(
                f"Entry {idx} (ID: {entry.item_id}) is already pinned.",
                command="pin already pinned",
                replacements={"n": idx, "id": entry.item_id},
            )
            return
        set_pinned(entry.id, True)
        default_msg = f'Pinned entry {idx} (ID: {entry.item_id}).'
        print_success(
            default_msg,
            command="pin",
            replacements={"n": idx, "id": entry.item_id},
        )

    _run(action)


@app.command("unpin")
def unpin_command(target: Optional[str] = typer.Argument(None, help="Index or 10-digit ID")) -> None:
    def action() -> None:
        if not target:
            raise CliptError("Provide an index or 10-digit ID to unpin: clipt unpin <index|id>", command="unpin no input")
        idx, entry = _resolve_entry_or_error(target, command="unpin index out of range")
        if not entry.pinned:
            raise CliptError(
                f'Entry {idx} is not pinned.',
                command="unpin not pinned",
                replacements={"n": idx, "id": entry.item_id},
            )
        set_pinned(entry.id, False)
        default_msg = f'Unpinned entry {idx} (ID: {entry.item_id}).'
        print_success(
            default_msg,
            command="unpin",
            replacements={"n": idx, "id": entry.item_id},
        )

    _run(action)


@app.command("pins")
def pins_command() -> None:
    def action() -> None:
        entries = list_history(pinned_only=True)
        if not entries:
            print_warning("No pinned entries found.")
            return
        console.print(_history_table(entries, title="Pinned Clipboard Entries"))

    _run(action)


@app.command("share", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def share_command(ctx: typer.Context) -> None:
    raw_args = [a for a in _extract_raw_command_args("share", ctx) if a.strip()]

    def action() -> None:
        target_content = None
        is_piped = False

        if not raw_args:
            # 1. Check for piped input (e.g., ls | clipt share)
            if not sys.stdin.isatty():
                piped = sys.stdin.read()
                if piped and piped.strip():
                    target_content = strip_ansi(piped)
                    is_piped = True

            # 2. If no piped input, load the complete previous command response
            if not target_content:
                latest = latest_entry()
                content = read_clipboard()
                if latest and latest.content and latest.content.strip():
                    target_content = latest.content
                elif content and content.strip():
                    target_content = content
                else:
                    raise CliptError(
                        "No content to share. No previous command response found in history or clipboard.",
                        command="share empty",
                    )
        else:
            # 3. Check if a single argument is an Index or 10-digit ID
            if len(raw_args) == 1:
                resolved = _try_resolve_entry(raw_args[0])
                if resolved is not None:
                    _, entry = resolved
                    target_content = entry.content

            # 3. Check if argument(s) represent a terminal command or normal string
            if target_content is None:
                first_token = raw_args[0].lower()
                is_known_cmd = (
                    shutil.which(raw_args[0]) is not None
                    or first_token in {
                        "ls", "dir", "cat", "echo", "pwd", "grep", "date",
                        "git", "python", "ping", "ipconfig", "curl", "wget",
                        "type", "get-childitem", "get-date", "get-process"
                    }
                )

                if is_known_cmd:
                    exit_code, output = _run_and_tee_subprocess(raw_args)
                    if output and output.strip():
                        target_content = output
                    else:
                        print_warning("Command produced no output to share.")
                        if exit_code != 0:
                            raise typer.Exit(exit_code)
                        return
                else:
                    # Normal string
                    target_content = " ".join(raw_args)

        prompt_stream = None
        tty_file = None
        proceed_without_confirm = False

        if is_piped:
            tty_dev = "CONIN$" if sys.platform == "win32" else "/dev/tty"
            try:
                tty_file = open(tty_dev, "r", encoding="utf-8")
                prompt_stream = _TerminalStream(tty_file)
            except OSError:
                proceed_without_confirm = True

        if proceed_without_confirm:
            print_warning("No controlling terminal available for confirmation. Proceeding with upload...")
        else:
            try:
                confirmed = Confirm.ask(
                    f"Upload '{preview(target_content)}' to paste.rs?",
                    default=False,
                    stream=prompt_stream,
                )
            finally:
                if tty_file is not None:
                    try:
                        tty_file.close()
                    except Exception:
                        pass

            if not confirmed:
                print_warning("Upload cancelled.")
                return

        with console.status("[bold cyan]Uploading text..."):
            url = share_text(target_content)

        write_clipboard(url)
        _save_if_enabled(url, "share")
        default_msg = f"Uploaded to paste.rs. Link copied to clipboard:\n{url}"
        print_success(default_msg, command="share (paste.rs)", replacements={"url": url})

    _run(action)


@app.command("clear")
def clear_command() -> None:
    def action() -> None:
        unpinned = count_history(unpinned_only=True)
        pinned = count_history(pinned_only=True)
        if unpinned == 0:
            print_info("No unpinned history entries to clear.", command="clear nothing to clear")
            return
        if not Confirm.ask(
            f"Delete {unpinned} unpinned history entries?",
            default=False,
        ):
            print_warning("Operation cancelled. Clipboard and history unchanged.")
            return
        write_clipboard("")
        deleted = wipe_unpinned()
        default_msg = f"Cleared {deleted} unpinned entries. Kept {pinned} pinned entries."
        print_success(
            default_msg,
            command="clear",
            replacements={"deleted": deleted, "pinned": pinned},
        )

    _run(action)


@app.command("kaboom")
def kaboom_command() -> None:
    def action() -> None:
        total = count_history()
        if total == 0:
            print_info("History is already empty.", command="kaboom nothing to wipe")
            return
        choice = Prompt.ask(
            f"Permanently delete all {total} history entries (including pinned items)?",
            choices=["Kaboom!", "Cancel"],
            default="Cancel",
            case_sensitive=False,
        )
        if choice.strip().lower() != "kaboom!":
            print_warning("Operation cancelled. History unchanged.")
            return
        write_clipboard("")
        deleted = wipe_all()
        default_msg = f"Deleted all {deleted} history entries."
        print_success(
            default_msg,
            command="kaboom",
            replacements={"deleted": deleted},
        )

    _run(action)


@app.command("kill")
def kill_command(target: Optional[str] = typer.Argument(None, help="Index or 10-digit ID")) -> None:
    def action() -> None:
        if not target:
            raise CliptError("Provide an index or 10-digit ID to delete: clipt kill <index|id>", command="kill no input")
        idx, entry = _resolve_entry_or_error(target, command="kill index out of range")
        if entry.pinned:
            raise CliptError(
                "Cannot delete a pinned entry. Unpin it first.",
                command="kill trying to delete a pinned item",
                replacements={"n": idx, "id": entry.item_id},
            )
        if not Confirm.ask(
            f"Delete entry {idx} ('{preview(entry.content)}')?",
            default=False,
        ):
            print_warning("Deletion cancelled.")
            return
        delete_history_entry(entry.id)
        default_msg = f"Deleted entry {idx} (ID: {entry.item_id})."
        print_success(
            default_msg,
            command="kill",
            replacements={"n": idx, "id": entry.item_id},
        )

    _run(action)


@app.command("stats")
def stats_command() -> None:
    def action() -> None:
        data = db_stats()
        by_source = data["by_source"]
        source_table = Table(box=box.MINIMAL, show_header=False)
        source_table.add_column("Source", style="magenta")
        source_table.add_column("Count", justify="right")
        for source in ["manual", "pipe", "file", "ocopy", "share"]:
            source_table.add_row(source, str(dict(by_source).get(source, 0)))

        words = top_words(list(data["contents"]))
        words_text = "\n".join(f"{word}: {count}" for word, count in words) if words else "No entries recorded."
        dashboard = Table.grid(expand=True)
        dashboard.add_column(ratio=1)
        dashboard.add_column(ratio=1)
        dashboard.add_row(
            Panel(f"[bold]{data['total']}[/]\nTotal entries saved", border_style="cyan"),
            Panel(f"[bold]{data['avg_len']:.1f}[/]\nAverage entry length", border_style="green"),
        )
        dashboard.add_row(
            Panel(words_text, title="Top Words", title_align="center", border_style="magenta"),
            Panel(source_table, title="Entries by Source", title_align="center", border_style="yellow"),
        )
        dashboard.add_row(
            Panel(WEEKDAYS.get(str(data["busiest_day"]), "No entries recorded"), title="Busiest Day", title_align="center", border_style="blue"),
            Panel(f"Pinned entries: [bold]{data['pinned']}[/]", title_align="center", border_style="cyan"),
        )
        console.print(Panel(dashboard, title="[bold cyan]Clipboard Statistics[/]", title_align="center", border_style="cyan"))

    _run(action)


@app.command("init")
def init_command() -> None:
    def action() -> None:
        console.print("[bold cyan]Configuring system PATH for clipt...[/]")
        success, message = install_clipt()
        if success:
            default_msg = (
                f"{message}\n\n"
                f"Installation complete.\n\n"
                f"Restart your terminal or reload your shell configuration to apply PATH changes."
            )
            print_success(
                default_msg,
                command="init",
                replacements={"message": message},
            )
        else:
            raise CliptError(
                f"Installation failed:\n{message}",
                command="init",
                replacements={"message": message},
            )

    _run(action)


def _show_config_table(cfg: Config) -> None:
    table = Table(
        title="Configuration Settings",
        box=box.SIMPLE_HEAVY,
        header_style="bold cyan",
    )
    table.add_column("Setting", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="green", justify="center")
    table.add_column("Default", style="dim", justify="center")
    table.add_column("Type", style="magenta", justify="center")
    table.add_column("Description")

    for key, meta in CONFIG_METADATA.items():
        curr_val = getattr(cfg, key)
        curr_str = str(curr_val).lower() if isinstance(curr_val, bool) else str(curr_val)
        def_val = getattr(DEFAULT_CONFIG, key)
        def_str = str(def_val).lower() if isinstance(def_val, bool) else str(def_val)
        table.add_row(key, curr_str, def_str, meta["type"], meta["description"])

    console.print(table)
    console.print(f"  [dim]Config file: {CONFIG_PATH}[/dim]")
    console.print("  [dim]Tip: Use 'clipt --config <setting> <value>' to update, or 'clipt --config reset' to restore defaults.[/dim]")
    console.print()


def _safe_sym(sym: str, fallback: str) -> str:
    enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    try:
        sym.encode(enc)
        return sym
    except Exception:
        return fallback


def _read_terminal_key() -> str:
    if sys.platform == "win32":
        import msvcrt

        try:
            ch = msvcrt.getwch()
        except (KeyboardInterrupt, EOFError):
            return "escape"
        except Exception:
            return ""

        if ch == "\x03":  # Ctrl+C
            return "escape"
        if ch in ("\x00", "\xe0"):
            try:
                ch2 = msvcrt.getwch()
            except Exception:
                return ""
            if ch2 in ("H", "w"):
                return "up"
            elif ch2 in ("P", "s"):
                return "down"
            elif ch2 in ("K", "a"):
                return "left"
            elif ch2 in ("M", "d"):
                return "right"
            return ""
        elif ch in ("\r", "\n"):
            return "enter"
        elif ch == "\x1b":
            return "escape"
        elif ch == " ":
            return "space"
        elif ch in ("\x08", "\x7f"):
            return "backspace"
        return ch
    else:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
        except Exception:
            return ""
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x03":
                return "escape"
            if ch == "\x1b":
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r:
                    seq = sys.stdin.read(2)
                    if seq == "[A":
                        return "up"
                    elif seq == "[B":
                        return "down"
                    elif seq == "[C":
                        return "right"
                    elif seq == "[D":
                        return "left"
                return "escape"
            elif ch in ("\r", "\n"):
                return "enter"
            elif ch == " ":
                return "space"
            elif ch in ("\x7f", "\x08"):
                return "backspace"
            return ch
        except (KeyboardInterrupt, EOFError):
            return "escape"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _interactive_config_editor(initial_cfg: Config) -> None:
    cfg = initial_cfg
    keys = list(CONFIG_METADATA.keys())
    selected_idx = 0
    total_items = len(keys) + 2
    status_msg = "Ready"

    def _render() -> None:
        cur = _safe_sym("❯ ", "> ")
        cm = _safe_sym("✓", "*")
        lines: list[str] = []

        for i, k in enumerate(keys):
            sel = (i == selected_idx)
            pfx = cur if sel else "  "
            val = getattr(cfg, k)
            if isinstance(val, bool):
                val_str = "[bold green]true[/]" if val else "[bold red]false[/]"
            elif isinstance(val, int):
                val_str = f"[bold cyan]{val}[/]"
            else:
                val_str = f"[bold magenta]{val}[/]"

            m = CONFIG_METADATA[k]
            m_def = getattr(DEFAULT_CONFIG, k)
            m_def_str = str(m_def).lower() if isinstance(m_def, bool) else str(m_def)
            m_typ = m["type"]
            m_desc = m["description"]

            if sel:
                lines.append(f"{pfx}[bold white]{k}[/]: {val_str}  [dim](default: {m_def_str}, {m_typ})[/]")
                lines.append(f"    [white]{m_desc}[/]")
            else:
                lines.append(f"{pfx}[dim]{k}[/]: {val_str}  [dim](default: {m_def_str}, {m_typ})[/]")
                lines.append(f"    [dim]{m_desc}[/]")
            lines.append("")

        div = _safe_sym("─", "-") * 64
        lines.append(f"  {div}")

        pfx_reset = cur if selected_idx == len(keys) else "  "
        if selected_idx == len(keys):
            lines.append(f"{pfx_reset}[bold white]Reset all settings to defaults[/]")
        else:
            lines.append(f"{pfx_reset}[dim]Reset all settings to defaults[/]")

        pfx_exit = cur if selected_idx == len(keys) + 1 else "  "
        if selected_idx == len(keys) + 1:
            lines.append(f"{pfx_exit}[bold white]Save & Exit[/]")
        else:
            lines.append(f"{pfx_exit}[dim]Save & Exit[/]")

        body = "\n".join(lines)
        panel = Panel(
            body,
            title="[bold cyan]Settings Editor[/]",
            subtitle=f"[dim]Config file: {CONFIG_PATH}[/]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
        console.clear()
        console.print(panel)
        nav_sym = _safe_sym("↑/↓", "Up/Down")
        console.print(f"  [bold cyan][{nav_sym}][/] Navigate  |  [bold cyan][Enter][/] Toggle/Edit  |  [bold cyan]\\[r][/] Reset  |  [bold cyan][Esc/q][/] Save & Exit")
        console.print(f"  [bold green]{cm} {status_msg}[/]")

    while True:
        _render()
        key = _read_terminal_key()

        if key in ("escape", "q", "Q"):
            break

        elif key in ("up", "k", "K"):
            selected_idx = (selected_idx - 1) % total_items
            status_msg = "Ready"

        elif key in ("down", "j", "J"):
            selected_idx = (selected_idx + 1) % total_items
            status_msg = "Ready"

        elif key in ("1", "2", "3", "4", "5", "6"):
            selected_idx = int(key) - 1
            status_msg = "Ready"

        elif key in ("r", "R"):
            if selected_idx < len(keys):
                k = keys[selected_idx]
                def_val = getattr(DEFAULT_CONFIG, k)
                cfg, _ = set_config_value(k, def_val)
                def_disp = str(def_val).lower() if isinstance(def_val, bool) else str(def_val)
                status_msg = f"Reset {k} to default ({def_disp})."
            elif selected_idx == len(keys):
                reset_config()
                cfg = load_config()
                status_msg = "All settings reset to defaults."
            elif selected_idx == len(keys) + 1:
                break

        elif key in ("enter", "space"):
            if selected_idx < len(keys):
                k = keys[selected_idx]
                curr_val = getattr(cfg, k)
                if isinstance(curr_val, bool):
                    new_bool = not curr_val
                    cfg, _ = set_config_value(k, str(new_bool).lower())
                    status_msg = f"Updated {k} = {str(new_bool).lower()} (saved to config.toml)"
                elif k == "max_history_entries":
                    console.print()
                    console.print(f"  [bold cyan]Enter new value for {k}[/] [dim](current: {curr_val}, positive integer)[/]: ", end="")
                    try:
                        inp = input().strip()
                        if inp:
                            cfg, new_val = set_config_value(k, inp)
                            status_msg = f"Updated {k} = {new_val} (saved to config.toml)"
                        else:
                            status_msg = f"{k} unchanged."
                    except ValueError as exc:
                        status_msg = str(exc)
                    except (KeyboardInterrupt, EOFError):
                        status_msg = "Cancelled."
                elif k == "share_service":
                    console.print()
                    console.print(f"  [bold cyan]Enter share service[/] [dim](current: {curr_val}, available: paste.rs)[/]: ", end="")
                    try:
                        inp = input().strip()
                        if inp:
                            cfg, new_val = set_config_value(k, inp)
                            status_msg = f"Updated {k} = {new_val} (saved to config.toml)"
                        else:
                            status_msg = f"{k} unchanged."
                    except ValueError as exc:
                        status_msg = str(exc)
                    except (KeyboardInterrupt, EOFError):
                        status_msg = "Cancelled."
            elif selected_idx == len(keys):
                reset_config()
                cfg = load_config()
                status_msg = "All settings reset to defaults."
            elif selected_idx == len(keys) + 1:
                break

    console.clear()
    print_success(f"Configuration saved to {CONFIG_PATH}", command="config")


def _show_config_help() -> None:
    console.print("Usage: clipt --config [SETTING] [VALUE]")
    console.print()
    console.print("View or update clipt configuration settings.")
    console.print()
    console.print("Options / Subcommands:")
    console.print("  clipt --config                          Open interactive settings editor (or view table)")
    console.print("  clipt --config list                     View settings in static table")
    console.print("  clipt --config <setting>                View current value of a setting")
    console.print("  clipt --config <setting> <value>        Update a setting value")
    console.print("  clipt --config set <setting> <value>    Explicitly update a setting value")
    console.print("  clipt --config get <setting>            Explicitly get a setting value")
    console.print("  clipt --config reset                    Restore default settings")
    console.print("  clipt --config path                     Show configuration file path")
    console.print()


@app.command("config", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def config_command(ctx: typer.Context) -> None:
    """View or change configuration settings."""
    raw_args = [a for a in _extract_raw_command_args("config", ctx) if a.strip()]

    def action() -> None:
        cfg = load_config()

        if not raw_args:
            if sys.stdin.isatty():
                _interactive_config_editor(cfg)
            else:
                _show_config_table(cfg)
            return

        first = raw_args[0].lower().lstrip("-")

        if first in {"help", "h"}:
            _show_config_help()
            return

        if first in {"interactive", "edit"}:
            _interactive_config_editor(cfg)
            return

        if first in {"reset"}:
            reset_config()
            print_success("Configuration reset to default settings.", command="config")
            return

        if first in {"path"}:
            console.print(str(CONFIG_PATH))
            return

        if first in {"list", "table", "show"}:
            _show_config_table(cfg)
            return

        def _apply_set(key: str, value: str) -> None:
            key = key.strip()
            try:
                _, new_val = set_config_value(key, value)
            except (KeyError, ValueError) as exc:
                raise CliptError(str(exc), command="config") from None
            val_display = str(new_val).lower() if isinstance(new_val, bool) else str(new_val)
            print_success(f"Configuration updated: {key} = {val_display}", command="config")

        if first == "get":
            if len(raw_args) < 2:
                raise CliptError("Provide a setting name: clipt --config get <setting>", command="config")
            key = raw_args[1].strip()
            if key not in CONFIG_METADATA:
                valid_keys = ", ".join(CONFIG_METADATA.keys())
                raise CliptError(f"Unknown configuration setting '{key}'. Valid settings: {valid_keys}.", command="config")
            val = getattr(cfg, key)
            val_str = str(val).lower() if isinstance(val, bool) else str(val)
            console.print(f"[bold cyan]{key}[/] = [green]{val_str}[/]")
            return

        if first == "set":
            if len(raw_args) == 2 and "=" in raw_args[1]:
                k, v = raw_args[1].split("=", 1)
                _apply_set(k, v)
                return
            if len(raw_args) < 3:
                raise CliptError("Provide setting and value: clipt --config set <setting> <value>", command="config")
            _apply_set(raw_args[1], " ".join(raw_args[2:]))
            return

        if "=" in raw_args[0]:
            k, v = raw_args[0].split("=", 1)
            _apply_set(k, v)
            return

        if len(raw_args) == 1:
            key = raw_args[0].strip()
            if key in CONFIG_METADATA:
                val = getattr(cfg, key)
                val_str = str(val).lower() if isinstance(val, bool) else str(val)
                console.print(f"[bold cyan]{key}[/] = [green]{val_str}[/]")
                return
            valid_keys = ", ".join(CONFIG_METADATA.keys())
            raise CliptError(f"Unknown configuration setting '{key}'. Valid settings: {valid_keys}.", command="config")

        _apply_set(raw_args[0], " ".join(raw_args[1:]))

    _run(action)


@app.command("version")
def version_command() -> None:
    def action() -> None:
        console.print(
            Panel(
                f"[bold cyan]clipt[/] {__version__}\nPython {platform.python_version()}",
                title="Version",
                title_align="center",
                border_style="cyan",
            )
        )

    _run(action)


@app.command("uninstall")
def uninstall_command() -> None:
    """Completely remove clipt and all its data from the system."""
    def action() -> None:
        if not Confirm.ask(
            "Are you sure you want to permanently uninstall clipt and all its data?",
            default=False,
        ):
            print_warning("Uninstallation cancelled. clipt remains installed.")
            return

        console.print("[bold red]Removing clipt from your system...[/]")
        success, message = uninstall_clipt()
        if success:
            default_msg = f"{message}\n\nclipt and all associated data have been completely removed."
            print_success(
                default_msg,
                command="uninstall",
                replacements={"message": message},
            )
        else:
            raise CliptError(
                f"Failed to completely remove clipt:\n{message}",
                command="uninstall",
                replacements={"message": message},
            )

    _run(action)


def run_cli(args: list[str] | None = None) -> None:
    if args is None:
        args = sys.argv[1:]

    if not args:
        show_help()
        return

    flag = args[0]
    if flag in {"--version", "-v"}:
        args[0] = "version"
    elif flag in {"--help", "-h"}:
        args[0] = "help"
    elif flag == "--init":
        args[0] = "init"
    elif flag == "--uninstall":
        args[0] = "uninstall"
    elif flag in {"--config", "-c"}:
        args[0] = "config"

    sys.argv = [sys.argv[0]] + args
    app(prog_name="clipt")


def main() -> None:
    run_cli()


if __name__ == "__main__":
    main()

