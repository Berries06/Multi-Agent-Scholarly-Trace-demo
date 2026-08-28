"""PyInstaller entry point for the FastAPI-backed PyQt desktop client."""

from yanhai.qt_app import main


if __name__ == "__main__":
    raise SystemExit(main())
