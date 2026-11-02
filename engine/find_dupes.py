r"""find_dupes.py - command-line entry point for dupefinder/finder.py.

Run from a copy of the whole repository, for example:
  py engine\find_dupes.py --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder.finder import main  # noqa: E402

if __name__ == "__main__":
    main()
