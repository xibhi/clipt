from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return platform.system() == "Windows"


def _check_mark() -> str:
    enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    try:
        "✓".encode(enc)
        return "✓"
    except Exception:
        return "*"


def _warn_mark() -> str:
    enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    try:
        "⚠".encode(enc)
        return "⚠"
    except Exception:
        return "!"


PERSISTENT_DATA_DIR = Path.home() / ".local" / "share" / "clipt"
PERSISTENT_APP_DIR = PERSISTENT_DATA_DIR / "app"


def get_base_python() -> str:
    """Resolve the permanent host Python interpreter, bypassing any project-local virtualenvs."""
    base = getattr(sys, "_base_executable", None)
    if base and os.path.exists(base):
        return base
    base_prefix = getattr(sys, "base_prefix", None) or sys.prefix
    if is_windows():
        candidate = Path(base_prefix) / "python.exe"
        if candidate.exists():
            return str(candidate)
    else:
        for name in ("python3", "python"):
            candidate = Path(base_prefix) / "bin" / name
            if candidate.exists():
                return str(candidate)
    return sys.executable


def _sync_persistent_app() -> tuple[bool, str]:
    """
    Ensure clipt and its dependencies are persistently installed into
    ~/.local/share/clipt/app so clipt remains fully functional even if
    the cloned source code directory or local .venv is deleted.
    """
    import importlib.util
    import shutil

    try:
        PERSISTENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        PERSISTENT_APP_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Synchronize clipt package files into PERSISTENT_APP_DIR / "clipt"
        source_root = Path(__file__).resolve().parent
        target_pkg = PERSISTENT_APP_DIR / "clipt"
        target_pkg.mkdir(parents=True, exist_ok=True)

        py_files = [
            "__init__.py",
            "__main__.py",
            "main.py",
            "config.py",
            "db.py",
            "hooks.py",
            "message_manager.py",
            "utils.py",
        ]
        for pf in py_files:
            src_file = source_root / pf
            if src_file.exists():
                shutil.copy2(src_file, target_pkg / pf)

        src_msg = source_root / ".clipt-messages"
        if src_msg.exists():
            target_msg = target_pkg / ".clipt-messages"
            if target_msg.exists():
                shutil.rmtree(target_msg, ignore_errors=True)
            shutil.copytree(src_msg, target_msg)

        # 2. Copy runtime dependency packages from current environment to PERSISTENT_APP_DIR
        dep_modules = [
            "typer",
            "rich",
            "pyperclip",
            "requests",
            "urllib3",
            "idna",
            "certifi",
            "charset_normalizer",
            "shellingham",
            "markdown_it",
            "mdurl",
            "pygments",
            "tomli",
            "click",
            "typing_extensions",
        ]
        for mod_name in dep_modules:
            try:
                spec = importlib.util.find_spec(mod_name)
                if spec and spec.origin:
                    origin_path = Path(spec.origin)
                    if origin_path.name == "__init__.py":
                        pkg_dir = origin_path.parent
                        dest = PERSISTENT_APP_DIR / pkg_dir.name
                        if not dest.exists():
                            shutil.copytree(
                                pkg_dir,
                                dest,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                            )
                    elif origin_path.suffix == ".py":
                        dest = PERSISTENT_APP_DIR / origin_path.name
                        if not dest.exists():
                            shutil.copy2(origin_path, dest)
            except Exception:
                pass

        return True, f"Synchronized persistent application files to {PERSISTENT_APP_DIR}"
    except Exception as exc:
        return False, f"Could not establish persistent app directory: {exc}"


def install_clipt() -> tuple[bool, str]:
    """
    Install clipt command for system-wide access across platforms (Windows & POSIX).
    Syncs persistent application files to ~/.local/share/clipt/app so clipt remains
    available even if the original cloned repository or local .venv is deleted.
    Returns (success: bool, message: str).
    """
    sync_ok, sync_msg = _sync_persistent_app()

    if is_windows():
        success, msg = _install_windows()
    else:
        success, msg = _install_posix()

    if sync_ok and sync_msg:
        cm = _check_mark()
        msg = f"{cm} {sync_msg}\n{msg}"
    elif not sync_ok and sync_msg:
        wm = _warn_mark()
        msg = f"{wm} {sync_msg}\n{msg}"
    return success, msg


def _is_safe_system_python(py_path: Path) -> bool:
    """
    Verify sys.executable resolves to a path NOT under Path.home()
    and not otherwise writable by the current user.
    """
    try:
        resolved = py_path.resolve()
        home = Path.home().resolve()
        try:
            resolved.relative_to(home)
            return False
        except ValueError:
            pass

        if not resolved.exists():
            return False

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            st = resolved.stat()
            return st.st_uid == 0 and not bool(st.st_mode & 0o002)

        return not os.access(resolved, os.W_OK)
    except Exception:
        return False


def _install_posix() -> tuple[bool, str]:
    """Install clipt on POSIX systems (Linux, macOS)."""
    results: list[str] = []
    errors: list[str] = []

    # 1. Determine and create binary directory
    python_exe = get_base_python()
    install_dir = None
    if _is_safe_system_python(Path(python_exe)):
        install_dirs = [
            Path("/usr/local/bin"),
            Path("/usr/bin"),
        ]
        for directory in install_dirs:
            if directory.exists() and os.access(directory, os.W_OK):
                install_dir = directory
                break

    needs_path_export = False
    if not install_dir:
        local_bin = Path.home() / ".local" / "bin"
        try:
            local_bin.mkdir(parents=True, exist_ok=True)
            if os.access(local_bin, os.W_OK):
                install_dir = local_bin
                needs_path_export = True
            else:
                return False, f"Permission denied creating/writing to {local_bin}"
        except Exception as exc:
            return False, f"Could not create {local_bin}: {exc}"

    # 2. Write wrapper script
    clipt_script = install_dir / "clipt"
    app_dir = PERSISTENT_APP_DIR
    wrapper_content = f"""#!/bin/sh
# clipt - Clipboard manager wrapper
# Auto-generated by: clipt --init

if [ -n "$PYTHONPATH" ]; then
    export PYTHONPATH="{app_dir}:$PYTHONPATH"
else
    export PYTHONPATH="{app_dir}"
fi
exec "{python_exe}" -m clipt "$@"
"""
    try:
        clipt_script.write_text(wrapper_content, encoding="utf-8")
        clipt_script.chmod(0o755)
        cm = _check_mark()
        results.append(f"{cm} clipt wrapper installed to {clipt_script}")
    except Exception as exc:
        return False, f"Failed to write executable wrapper {clipt_script}: {exc}"

    # 3. Update shell configuration files if local_bin is used
    if needs_path_export:
        shells_updated = _update_posix_shell_configs(install_dir)
        cm = _check_mark()
        if shells_updated:
            results.append(f"{cm} Added {install_dir} to PATH in: {', '.join(shells_updated)}")
        else:
            results.append(f"{cm} {install_dir} configured in PATH")

    summary = "\n".join(results)
    if errors:
        wm = _warn_mark()
        summary += "\n" + "\n".join(f"{wm} {err}" for err in errors)
    return True, summary


WRAPPER_MARKER = "# clipt - Clipboard manager wrapper"
WRAPPER_MARKER_ALT = "# Auto-generated by: clipt --init"
SHELL_MARKER_START = "# === CLIPT CLI PATH HOOK START (clipt-clipboard-manager) ==="
SHELL_MARKER_END = "# === CLIPT CLI PATH HOOK END (clipt-clipboard-manager) ==="
LEGACY_SHELL_MARKER_START = "# === CLIPT START ==="
LEGACY_SHELL_MARKER_END = "# === CLIPT END ==="


def _is_clipt_wrapper(path: Path) -> bool:
    """Verify that a target script or config was generated by clipt before removing it."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return (
            WRAPPER_MARKER in content
            or ":: clipt - Clipboard manager wrapper" in content
            or "Auto-generated by: clipt" in content
            or SHELL_MARKER_START in content
            or LEGACY_SHELL_MARKER_START in content
        )
    except Exception:
        return False


def _clean_shell_content(content: str) -> tuple[str, bool]:
    """Clean both current and legacy clipt marker blocks from shell config content."""
    cleaned = False
    for m_start, m_end in [
        (SHELL_MARKER_START, SHELL_MARKER_END),
        (LEGACY_SHELL_MARKER_START, LEGACY_SHELL_MARKER_END),
    ]:
        if m_start in content:
            start_idx = content.find(m_start)
            end_idx = content.find(m_end)
            if end_idx != -1:
                content = (
                    content[:start_idx] + content[end_idx + len(m_end) :]
                ).strip()
                cleaned = True
    return content, cleaned


def _update_posix_shell_configs(bin_dir: Path) -> list[str]:
    shells_updated: list[str] = []
    home = Path.home()

    # Bash / Zsh configs
    sh_export = f'{SHELL_MARKER_START}\nexport PATH="{bin_dir}:$PATH"\n{SHELL_MARKER_END}\n'
    for sh_name, rc_file in [("bash", home / ".bashrc"), ("zsh", home / ".zshrc")]:
        if rc_file.exists():
            try:
                content = rc_file.read_text(encoding="utf-8")
                for m_start, m_end in [
                    (SHELL_MARKER_START, SHELL_MARKER_END),
                    (LEGACY_SHELL_MARKER_START, LEGACY_SHELL_MARKER_END),
                ]:
                    if m_start in content:
                        start_idx = content.find(m_start)
                        end_idx = content.find(m_end)
                        if end_idx != -1:
                            content = content[:start_idx] + content[end_idx + len(m_end) :].lstrip("\n")
                content = content.rstrip("\n") + "\n\n" + sh_export
                rc_file.write_text(content, encoding="utf-8")
                shells_updated.append(sh_name)
            except Exception:
                pass

    # Fish config
    fish_dir = home / ".config" / "fish" / "conf.d"
    fish_file = fish_dir / "clipt.fish"
    fish_content = (
        f"{WRAPPER_MARKER}\n"
        f"{WRAPPER_MARKER_ALT}\n"
        f"{SHELL_MARKER_START}\n"
        f"fish_add_path '{bin_dir}'\n"
        f"{SHELL_MARKER_END}\n"
    )
    try:
        fish_dir.mkdir(parents=True, exist_ok=True)
        fish_file.write_text(fish_content, encoding="utf-8")
        shells_updated.append("fish")
    except Exception:
        pass

    return shells_updated


def _install_windows() -> tuple[bool, str]:
    """Install clipt on Windows (PowerShell and cmd.exe)."""
    results: list[str] = []
    errors: list[str] = []

    # 1. Create local bin directory
    local_bin = Path.home() / ".local" / "bin"
    try:
        local_bin.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return False, f"Could not create {local_bin}: {exc}"

    # 2. Create cmd/bat wrapper and PowerShell script
    python_exe = get_base_python()
    app_dir = PERSISTENT_APP_DIR
    cmd_wrapper = local_bin / "clipt.cmd"
    ps_wrapper = local_bin / "clipt.ps1"

    cmd_content = (
        f":: clipt - Clipboard manager wrapper\r\n"
        f":: Auto-generated by: clipt --init\r\n"
        f"@echo off\r\n"
        f"if defined PYTHONPATH (\r\n"
        f"    set \"PYTHONPATH={app_dir};%PYTHONPATH%\"\r\n"
        f") else (\r\n"
        f"    set \"PYTHONPATH={app_dir}\"\r\n"
        f")\r\n"
        f"\"{python_exe}\" -m clipt %*\r\n"
    )
    ps_content = (
        f"# clipt - Clipboard manager wrapper\r\n"
        f"# Auto-generated by: clipt --init\r\n"
        f"if ($env:PYTHONPATH) {{\r\n"
        f"    $env:PYTHONPATH = \"{app_dir};$env:PYTHONPATH\"\r\n"
        f"}} else {{\r\n"
        f"    $env:PYTHONPATH = \"{app_dir}\"\r\n"
        f"}}\r\n"
        f"& \"{python_exe}\" -m clipt @args\r\n"
    )

    try:
        cmd_wrapper.write_text(cmd_content, encoding="utf-8")
        ps_wrapper.write_text(ps_content, encoding="utf-8")
        cm = _check_mark()
        results.append(f"{cm} clipt wrapper installed to {local_bin}")
    except Exception as exc:
        return False, f"Failed to write Windows wrappers to {local_bin}: {exc}"

    # 3. Update User PATH persistently via Windows Registry
    path_updated = _add_windows_user_path(str(local_bin))
    cm = _check_mark()
    if path_updated:
        results.append(f"{cm} Added {local_bin} to User PATH")

    # 4. Update PowerShell profile if found
    ps_profiles_updated = _update_powershell_profiles(local_bin)
    if ps_profiles_updated:
        results.append(f"{cm} Configured PowerShell profiles: {', '.join(ps_profiles_updated)}")

    summary = "\n".join(results)
    if errors:
        wm = _warn_mark()
        summary += "\n" + "\n".join(f"{wm} {err}" for err in errors)
    return True, summary


def _add_windows_user_path(directory: str) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current_path, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current_path = ""

            path_parts = [p.strip() for p in current_path.split(";") if p.strip()]
            norm_dir = os.path.normpath(directory).lower()
            if not any(os.path.normpath(p).lower() == norm_dir for p in path_parts):
                path_parts.append(directory)
                new_path = ";".join(path_parts)
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                return True
            return False
    except Exception:
        return False


def _update_powershell_profiles(local_bin: Path) -> list[str]:
    updated: list[str] = []
    ps_block = f'\n{SHELL_MARKER_START}\n$env:PATH = "{local_bin};$env:PATH"\n{SHELL_MARKER_END}\n'

    home = Path.home()
    profile_locations = [
        ("PowerShell 7+", home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"),
        ("Windows PowerShell", home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"),
    ]

    for label, profile_path in profile_locations:
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            existing_content = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
            for m_start, m_end in [
                (SHELL_MARKER_START, SHELL_MARKER_END),
                (LEGACY_SHELL_MARKER_START, LEGACY_SHELL_MARKER_END),
            ]:
                if m_start in existing_content:
                    start_idx = existing_content.find(m_start)
                    end_idx = existing_content.find(m_end)
                    if end_idx != -1:
                        existing_content = (
                            existing_content[:start_idx] + existing_content[end_idx + len(m_end) :]
                        ).lstrip("\n")

            new_content = existing_content.rstrip("\n") + "\n" + ps_block
            profile_path.write_text(new_content, encoding="utf-8")
            updated.append(label)
        except Exception:
            pass

    return updated


def _safe_rmtree(target: Path) -> bool:
    """Robustly delete directory tree on Windows and POSIX."""
    import shutil
    import stat

    if not target.exists():
        return True
    try:
        shutil.rmtree(target, ignore_errors=True)
    except Exception:
        pass
    if target.exists():
        try:
            for p in target.glob("**/*"):
                try:
                    os.chmod(p, stat.S_IWRITE)
                except Exception:
                    pass
            shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass
    return not target.exists()


def uninstall_clipt() -> tuple[bool, str]:
    """
    Completely remove clipt tool, wrappers, shell hooks, config, and data from the user system.
    Returns (success: bool, summary: str).
    """
    import shutil
    results: list[str] = []
    home = Path.home()
    cm = _check_mark()
    wm = _warn_mark()

    # 1. Remove data and config directories
    data_dir = home / ".local" / "share" / "clipt"
    if data_dir.exists():
        if _safe_rmtree(data_dir):
            results.append(f"{cm} Removed persistent application files and clipboard history")
        else:
            results.append(f"{wm} Partially removed {data_dir} (some files locked)")

    config_dir = home / ".config" / "clipt"
    if config_dir.exists():
        if _safe_rmtree(config_dir):
            results.append(f"{cm} Removed configuration directory")
        else:
            results.append(f"{wm} Partially removed {config_dir} (some files locked)")

    # 2. Remove wrapper binaries
    wrappers = [
        home / ".local" / "bin" / "clipt.cmd",
        home / ".local" / "bin" / "clipt.ps1",
        home / ".local" / "bin" / "clipt",
        Path("/usr/local/bin/clipt"),
        Path("/usr/bin/clipt"),
    ]
    for w in wrappers:
        if w.exists():
            try:
                if _is_clipt_wrapper(w):
                    w.unlink()
                    results.append(f"{cm} Removed executable wrapper: {w.name}")
                else:
                    results.append(f"{wm} Skipped {w}: not a clipt-generated file")
            except Exception:
                pass

    # 3. Clean PowerShell profiles
    ps_profiles = [
        home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]
    for p in ps_profiles:
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                content, cleaned = _clean_shell_content(content)
                if cleaned:
                    p.write_text(content + "\n" if content else "", encoding="utf-8")
                    results.append(f"{cm} Cleaned PowerShell profile: {p.parent.name}")
            except Exception:
                pass

    # 4. Clean POSIX shell profiles (.bashrc, .zshrc, fish)
    posix_rcs = [home / ".bashrc", home / ".zshrc"]
    for rc in posix_rcs:
        if rc.exists():
            try:
                content = rc.read_text(encoding="utf-8")
                content, cleaned = _clean_shell_content(content)
                if cleaned:
                    rc.write_text(content + "\n" if content else "", encoding="utf-8")
                    results.append(f"{cm} Cleaned {rc.name}")
            except Exception:
                pass

    fish_file = home / ".config" / "fish" / "conf.d" / "clipt.fish"
    if fish_file.exists():
        try:
            if _is_clipt_wrapper(fish_file):
                fish_file.unlink()
                results.append(f"{cm} Removed fish configuration")
            else:
                results.append(f"{wm} Skipped {fish_file}: not a clipt-generated file")
        except Exception:
            pass

    # 5. Uninstall Python package
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", "clipt"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            results.append(f"{cm} Uninstalled clipt Python package")
    except Exception:
        pass

    summary = "\n".join(results) if results else "clipt completely removed."
    return True, summary
