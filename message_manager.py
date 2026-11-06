"""
Clipt Message Manager - Integrates cycling success/error messages with clipt commands.

This module provides message cycling functionality for clipt, rotating through
multiple success and error messages for each command.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

def _find_messages_dir() -> Path:
    """
    Find the .clipt-messages directory by checking multiple possible locations.
    
    This is necessary because the directory location varies depending on installation method:
    - Development install (pip install -e): points to source directory
    - Normal install: .clipt-messages is inside the clipt package
    - Fallback: user's home directory
    """
    possible_locations = [
        # First: Inside the clipt package (preferred - works for all installations)
        Path(__file__).parent / ".clipt-messages",
        # Second: In the parent directory (legacy, for backward compatibility)
        Path(__file__).parent.parent / ".clipt-messages",
        # Third: User's home directory (fallback)
        Path.home() / ".clipt-messages",
    ]
    
    for location in possible_locations:
        if location.exists():
            return location
    
    # Return the first location (inside package) as the default
    return possible_locations[0]


MESSAGES_DIR = _find_messages_dir()
SUCCESS_FILE = MESSAGES_DIR / "success.txt"
ERROR_FILE = MESSAGES_DIR / "error.txt"
STATE_FILE = MESSAGES_DIR / ".message-state.json"

# Debug: Log the paths at module load time
import os as _os
if _os.environ.get("CLIPT_DEBUG"):
    print(f"[DEBUG] message_manager loaded", file=sys.stderr)
    print(f"[DEBUG]   __file__ = {Path(__file__)}", file=sys.stderr)
    print(f"[DEBUG]   MESSAGES_DIR = {MESSAGES_DIR}", file=sys.stderr)
    print(f"[DEBUG]   MESSAGES_DIR exists = {MESSAGES_DIR.exists()}", file=sys.stderr)
    print(f"[DEBUG]   SUCCESS_FILE = {SUCCESS_FILE}", file=sys.stderr)
    print(f"[DEBUG]   SUCCESS_FILE exists = {SUCCESS_FILE.exists()}", file=sys.stderr)


def get_next_message(message_type: str, command: str, replacements: Optional[dict] = None) -> Optional[str]:
    """
    Get the next cycling message for a command.
    
    Args:
        message_type: "success" or "error"
        command: Command name (e.g., "--copy", "--fetch / recall index out of range")
        replacements: Dict of placeholder replacements (e.g., {"n": 5, "max": 3})
    
    Returns:
        The next cycling message for this command, or None if not found
    """
    # Use direct file parsing (fallback method is more reliable)
    return _get_message_fallback(message_type, command, replacements)


def _get_message_fallback(message_type: str, command: str, replacements: Optional[dict] = None) -> Optional[str]:
    """
    Fallback method to get messages by parsing files directly.
    """
    try:
        message_file = SUCCESS_FILE if message_type == "success" else ERROR_FILE
        
        # Debug: Log the paths being checked
        import os
        if os.environ.get("CLIPT_DEBUG"):
            print(f"[DEBUG] Looking for message file: {message_file}", file=sys.stderr)
            print(f"[DEBUG] File exists: {message_file.exists()}", file=sys.stderr)
        
        if not message_file.exists():
            return None
        
        messages_dict = _parse_messages_file(message_file)
        messages = messages_dict.get(command, [])
        
        if not messages:
            return None
        
        # Get current index from state
        state = _load_state()
        key = f"{message_type}:{command}"
        current_index = state.get(key, 0)
        
        # Get message
        message = messages[current_index]
        
        # Update state
        next_index = (current_index + 1) % len(messages)
        state[key] = next_index
        _save_state(state)
        
        # Replace placeholders
        if replacements:
            for placeholder, value in replacements.items():
                message = message.replace(f"{{{placeholder}}}", str(value))
        
        return message
    
    except Exception as e:
        # Silently fail - return None so clipt can use default message
        import os
        if os.environ.get("CLIPT_DEBUG"):
            print(f"[DEBUG] Exception in _get_message_fallback: {e}", file=sys.stderr)
        return None


def _parse_messages_file(filepath: Path) -> dict:
    """Parse a messages file and return a dict of command -> [messages]."""
    messages = {}
    current_command = None
    current_messages = []
    
    try:
        content = filepath.read_text(encoding="utf-8")
        
        for line in content.split("\n"):
            line = line.strip()
            
            if line.startswith("#"):
                # Store previous command
                if current_command:
                    messages[current_command] = current_messages
                    
                    # Handle commands with "/" - create aliases
                    if "/" in current_command:
                        parts = current_command.split("/")
                        for part in parts:
                            part = part.strip()
                            if part:
                                messages[part] = current_messages
                
                current_command = line[1:].strip()
                current_messages = []
            
            elif line.startswith('"') and line.endswith('"'):
                current_messages.append(line[1:-1].replace("\\n", "\n"))
        
        # Store last command
        if current_command:
            messages[current_command] = current_messages
            if "/" in current_command:
                parts = current_command.split("/")
                for part in parts:
                    part = part.strip()
                    if part:
                        messages[part] = current_messages
    
    except Exception:
        pass
    
    return messages


def _load_state() -> dict:
    """Load message state from JSON file."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    """Save message state to JSON file."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_success_message(command: str, replacements: Optional[dict] = None) -> Optional[str]:
    """Get a cycling success message for a command."""
    return get_next_message("success", command, replacements)


def get_error_message(command: str, replacements: Optional[dict] = None) -> Optional[str]:
    """Get a cycling error message for a command."""
    return get_next_message("error", command, replacements)
