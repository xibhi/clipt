"""clipt: a terminal clipboard manager for developers."""

__version__ = "1.0.0"

try:
    import typer.rich_utils as _typer_rich_utils

    _typer_rich_utils.ALIGN_ERRORS_PANEL = "center"
    _typer_rich_utils.ALIGN_COMMANDS_PANEL = "center"
    _typer_rich_utils.ALIGN_OPTIONS_PANEL = "center"
except Exception:
    pass
