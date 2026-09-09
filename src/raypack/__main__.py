from __future__ import annotations

import sys

from .cli import main as cli_main
from .gui import main as gui_main


def main() -> int:
    if len(sys.argv) > 1:
        return cli_main(sys.argv[1:])
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
