r"""compare_backup_sets.py - command-line entry point for dupefinder/backup_sets.py.

Run from a copy of the whole repository, for example:
  py engine\compare_backup_sets.py --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder.backup_sets import main  # noqa: E402

if __name__ == "__main__":
    main()
