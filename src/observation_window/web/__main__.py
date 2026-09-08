"""Entry point for `python -m observation_window.web`."""
from observation_window.web.server import main
import sys

if __name__ == "__main__":
    sys.exit(main())
