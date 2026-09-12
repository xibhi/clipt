"""Entry point for clipt when run as a module."""
try:
    from .main import run_cli
except ImportError:
    from main import run_cli

if __name__ == "__main__":
    run_cli()
