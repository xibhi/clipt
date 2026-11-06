from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_DIR = Path.home() / ".config" / "clipt"
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass(frozen=True)
class Config:
    max_history_entries: int = 500
    auto_save_history: bool = True
    deduplicate_consecutive: bool = True
    share_service: str = "paste.rs"


DEFAULT_CONFIG = Config()

CONFIG_METADATA: dict[str, dict[str, str]] = {
    "max_history_entries": {
        "type": "integer",
        "description": "Maximum number of history entries to retain",
    },
    "auto_save_history": {
        "type": "boolean",
        "description": "Automatically save copied text to history",
    },
    "deduplicate_consecutive": {
        "type": "boolean",
        "description": "Prevent duplicate consecutive entries in history",
    },
    "share_service": {
        "type": "string",
        "description": "Default paste service for sharing (paste.rs)",
    },
}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def load_config() -> Config:
    # BUG FIX: read the live share_service setting, while accepting the legacy key.
    ensure_config()
    try:
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_CONFIG

    share_service = str(
        data.get("share_service", data.get("default_share_service", DEFAULT_CONFIG.share_service))
    ).strip()
    if share_service != "paste.rs":
        share_service = DEFAULT_CONFIG.share_service

    config = Config(
        max_history_entries=_coerce_int(data.get("max_history_entries"), DEFAULT_CONFIG.max_history_entries),
        auto_save_history=_coerce_bool(data.get("auto_save_history"), DEFAULT_CONFIG.auto_save_history),
        deduplicate_consecutive=_coerce_bool(
            data.get("deduplicate_consecutive"),
            DEFAULT_CONFIG.deduplicate_consecutive,
        ),
        share_service=share_service,
    )
    if "share_service" not in data and "default_share_service" in data:
        save_config(config)
    return config


def save_config(config: Config) -> None:
    # BUG FIX: persist the selected uploader under the documented share_service key.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        "\n".join(
            [
                f"max_history_entries = {config.max_history_entries}",
                f"auto_save_history = {str(config.auto_save_history).lower()}",
                f"deduplicate_consecutive = {str(config.deduplicate_consecutive).lower()}",
                f'share_service = "{config.share_service}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def ensure_config() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
    else:
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        val = value.strip().lower()
        if val in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if val in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
    raise ValueError(f"Cannot parse '{value}' as boolean (use true or false).")


def set_config_value(key: str, raw_value: Any) -> tuple[Config, Any]:
    key = key.strip()
    if key not in CONFIG_METADATA:
        valid_keys = ", ".join(CONFIG_METADATA.keys())
        raise KeyError(f"Unknown configuration setting '{key}'. Valid settings: {valid_keys}.")

    cfg = load_config()

    if key == "max_history_entries":
        try:
            val = int(raw_value)
            if val <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Invalid value '{raw_value}' for max_history_entries. Must be a positive integer.")
    elif key in ("auto_save_history", "deduplicate_consecutive"):
        try:
            val = parse_bool(raw_value)
        except ValueError:
            raise ValueError(f"Invalid value '{raw_value}' for {key}. Must be 'true' or 'false'.")
    elif key == "share_service":
        val = str(raw_value).strip().lower()
        if val != "paste.rs":
            raise ValueError(f"Invalid value '{raw_value}' for share_service. Supported services: paste.rs.")
    else:
        val = raw_value

    new_cfg = replace(cfg, **{key: val})
    save_config(new_cfg)
    return new_cfg, val


def reset_config() -> Config:
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG

