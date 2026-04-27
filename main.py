"""Entrada única do Soll v7.

Uso:
    python main.py            # CLI (chat com o agente — modo dev)
    python main.py cli        # idem, aceita flags do soll-cli (ex.: --user 5579999)
    python main.py server     # FastAPI / webhook Z-API em :8000
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"cli", "server"}:
        mode = sys.argv[1]
        sys.argv = [sys.argv[0], *sys.argv[2:]]
    else:
        mode = "cli"

    if mode == "server":
        from soll.api.webhook import main as run_server

        run_server()
    else:
        from soll.cli import main as run_cli

        run_cli()


if __name__ == "__main__":
    main()
