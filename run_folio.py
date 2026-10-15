"""Launcher used by PyInstaller (keeps the worker-process entry guarded)."""

from folio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
