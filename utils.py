from __future__ import annotations

import contextlib
import math
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pyperclip
import requests
from rich.console import Console
from rich.panel import Panel


console = Console(stderr=False)
err_console = Console(stderr=True)


class CliptError(Exception):
    """User-facing clipt error shown without a Python traceback.
    
    Can optionally include a command name for cycling error messages.
    """
    def __init__(self, message: str, command: str = None, replacements: dict = None):
        super().__init__(message)
        self.command = command
        self.replacements = replacements or {}


@contextlib.contextmanager
def _suppress_native_stderr():
    saved_fd = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(saved_fd)


ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1B  # ESC
    (?:   # 7-bit C1 Fe (except CSI)
        [@-Z\\-_]
    |     # or [ for CSI, followed by a control sequence
        \[
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    |     # or ] for OSC (Operating System Command) sequences
        \]
        [^\x07\x1b]* # OSC content
        (?:\x07|\x1B\\)?
    )
    """,
    re.VERBOSE,
)


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences, color codes, and terminal formatting."""
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


def preview(text: str, length: int = 60) -> str:
    clean = strip_ansi(text)
    compact = clean.replace("\r", "").replace("\n", " ")
    compact = re.sub(r"\s+", " ", compact).strip()
    if len(compact) <= length:
        return compact
    return compact[: max(0, length - 1)] + "…"


def read_clipboard() -> str:
    # BUG FIX: query pyperclip on every call so cleared clipboard state is never stale.
    try:
        with _suppress_native_stderr():
            return pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        raise CliptError(clipboard_help(str(exc))) from exc


def write_clipboard(text: str) -> None:
    try:
        with _suppress_native_stderr():
            pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        raise CliptError(clipboard_help(str(exc))) from exc


def clipboard_help(message: str) -> str:
    return (
        f"{message}\n\n"
        "Linux clipboard support requires xclip or xsel:\n"
        "  Debian/Ubuntu: sudo apt install xclip\n"
        "  Arch:          sudo pacman -S xclip"
    )




def share_text(text: str, preferred: str = "paste.rs") -> str:
    return _share_paste_rs(text)


def _share_paste_rs(text: str) -> str:
    try:
        response = requests.post(
            "https://paste.rs",
            data=text.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=12,
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise CliptError("Upload timed out. Check your network connection.", command="share upload failed (paste.rs)")
    except requests.exceptions.ConnectionError as exc:
        raise CliptError(f"Failed to connect to paste.rs: {exc}", command="share upload failed (paste.rs)")
    except requests.exceptions.HTTPError as exc:
        raise CliptError(f"Upload failed: {exc}", command="share upload failed (paste.rs)")
    except Exception as exc:
        raise CliptError(f"Upload failed: {exc}", command="share upload failed (paste.rs)")
    url = response.text.strip()
    try:
        parsed = urlparse(url)
        is_valid = parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() == "paste.rs"
    except Exception:
        is_valid = False

    if not is_valid:
        raise CliptError("paste.rs did not return a valid URL.", command="share upload failed (paste.rs)")
    return url


def _is_sensitive_token(word: str) -> bool:
    w_lower = word.lower()
    if len(word) > 25:
        return True
    sensitive_patterns = (
        "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
        "xoxb_", "xoxp_", "sk_", "akia", "eyjh",
        "bearer", "password", "passwd", "secret",
        "apikey", "api_key", "token", "auth_", "private_key",
    )
    if any(pattern in w_lower for pattern in sensitive_patterns):
        return True
    digits = sum(c.isdigit() for c in word)
    if len(word) >= 8 and (digits / len(word)) >= 0.3:
        return True
    if len(word) >= 16 and all(c in "0123456789abcdef" for c in w_lower):
        return True
    if len(word) >= 16:
        counts = Counter(w_lower)
        entropy = -sum((c / len(w_lower)) * math.log2(c / len(w_lower)) for c in counts.values())
        if entropy > 3.2:
            return True
    return False


def top_words(contents: list[str], limit: int = 5) -> list[tuple[str, int]]:
    words = re.findall(r"[A-Za-z0-9_]{2,}", "\n".join(contents).lower())
    stop = {"the", "and", "for", "with", "this", "that", "from", "http", "https"}
    counter = Counter(word for word in words if word not in stop and not _is_sensitive_token(word))
    return counter.most_common(limit)


def print_error(message: str, command: str = None, replacements: dict = None) -> None:
    """
    Print an error message. If command is provided, use a cycling message instead.
    
    Args:
        message: Default message to display (used if command cycling is not available)
        command: Optional command name for cycling messages (e.g., "--qr clipboard is not a URL")
        replacements: Optional dict for placeholder replacement
    """
    # Try to get a cycling message if command is provided
    cycling_message = None
    if command:
        try:
            try:
                from . import message_manager
            except ImportError:
                import message_manager
            cycling_message = message_manager.get_error_message(command, replacements)
        except Exception:
            # Fallback to default message if cycling system fails
            pass
    
    # Use cycling message if available, otherwise use provided message
    display_message = cycling_message if cycling_message else message
    err_console.print(Panel(str(display_message), title="[bold red]Error[/]", title_align="center", border_style="red"))


def print_warning(message: str) -> None:
    console.print(Panel(str(message), title="[bold yellow]Warning[/]", title_align="center", border_style="yellow"))


def print_info(message: str, command: str = None, replacements: dict = None) -> None:
    """
    Print an info message. If command is provided, use a cycling message instead.
    Similar to print_success but uses cyan/blue styling.
    
    Args:
        message: Default message to display (used if command cycling is not available)
        command: Optional command name for cycling messages (e.g., "--count")
        replacements: Optional dict for placeholder replacement
    """
    # Try to get a cycling message if command is provided
    cycling_message = None
    if command:
        try:
            try:
                from . import message_manager
            except ImportError:
                import message_manager
            cycling_message = (
                message_manager.get_success_message(command, replacements)
                or message_manager.get_error_message(command, replacements)
            )
        except Exception:
            # Fallback to default message if cycling system fails
            pass
    
    # Use cycling message if available, otherwise use provided message
    display_message = cycling_message if cycling_message else message
    console.print(Panel(str(display_message), title="[bold cyan]Info[/]", title_align="center", border_style="cyan"))


def print_success(message: str, command: str = None, replacements: dict = None) -> None:
    """
    Print a success message. If command is provided, use a cycling message instead.
    
    Args:
        message: Default message to display (used if command cycling is not available)
        command: Optional command name for cycling messages (e.g., "--copy")
        replacements: Optional dict for placeholder replacement
    """
    # Try to get a cycling message if command is provided
    cycling_message = None
    if command:
        try:
            try:
                from . import message_manager
            except ImportError:
                import message_manager
            cycling_message = message_manager.get_success_message(command, replacements)
        except Exception:
            # Fallback to default message if cycling system fails
            pass
    
    # Use cycling message if available, otherwise use provided message
    display_message = cycling_message if cycling_message else message
    console.print(Panel(str(display_message), title="[bold green]Success[/]", title_align="center", border_style="green"))


def read_text_file(path: Path, original_path: str | None = None) -> str:
    # Use as_posix() to show paths with forward slashes for consistency across platforms
    display_path = original_path or path.as_posix()
    if not path.exists():
        raise CliptError(
            f"File not found: '{display_path}'.",
            command="copy --file file not found",
            replacements={"path": display_path},
        )
    if not path.is_file():
        raise CliptError(f"Path is not a file: '{display_path}'.")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CliptError(
            f"Cannot copy '{display_path}': File is not a valid text file. Please provide a valid text file whose content can be copied.",
            command="copy --file not valid text",
            replacements={"path": display_path},
        ) from exc
