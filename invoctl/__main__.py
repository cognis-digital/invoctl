"""Enable `python -m invoctl`."""
import sys

from invoctl.cli import main

if __name__ == "__main__":
    sys.exit(main())
