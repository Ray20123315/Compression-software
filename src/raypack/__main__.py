from __future__ import annotations
import sys
from .cli import main as cli_main
from .gui import main as gui_main
if __name__ == '__main__':
    raise SystemExit(cli_main() if len(sys.argv)>1 else (gui_main() or 0))
