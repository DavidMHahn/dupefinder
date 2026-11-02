r"""quarantine_dupes.py - command-line entry point for dupefinder/quarantine.py.

Run from a copy of the whole repository, for example:
  py engine\quarantine_dupes.py --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder.quarantine import main  # noqa: E402

if __name__ == "__main__":
    main()
