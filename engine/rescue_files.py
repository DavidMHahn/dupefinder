r"""rescue_files.py - command-line entry point for dupefinder/rescue.py.

Run from a copy of the whole repository, for example:
  py engine\rescue_files.py --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder.rescue import main  # noqa: E402

if __name__ == "__main__":
    main()
