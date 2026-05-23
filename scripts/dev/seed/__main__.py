"""`python -m scripts.dev.seed` entry point. Defers to runner.main()."""

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
