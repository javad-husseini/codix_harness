"""PyInstaller entry point; stdin remains the private parent lifecycle channel."""
from backend.server import main

if __name__ == '__main__':
    raise SystemExit(main())
