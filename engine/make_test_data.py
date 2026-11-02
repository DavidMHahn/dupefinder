r"""make_test_data.py - command-line entry point for dupefinder/testdata.py.

Run from a copy of the whole repository, for example:
  py engine\make_test_data.py --help
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder.testdata import main  # noqa: E402

if __name__ == "__main__":
    main()
