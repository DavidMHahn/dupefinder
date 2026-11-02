"""Build a small folder with KNOWN duplicates, so you can check that the
finder finds exactly what it should.

  py make_test_data.py C:\\dupe_test

Creates (all random bytes, the same every time):
  3 copies of a 5 MB file                   -> 1 group, 10 MB wasted
  2 copies of a 200 KB file                 -> 1 group, 0.2 MB wasted
  2 copies of a 10 KB file                  -> 1 group, 0.01 MB wasted
  2 files of the same size, different start -> NOT duplicates (dropped at stage 3)
  2 files of the same size and same first
    64 KB but different endings             -> NOT duplicates (dropped at stage 4)
  20 unique files of different sizes        -> NOT duplicates (dropped at stage 2)
  1 empty file copied twice                 -> ignored (empty files are skipped)
"""

import os
import random
import sys

EXPECTED_GROUPS = 3
EXPECTED_FILES = 7
EXPECTED_WASTED = 2 * 5_000_000 + 200_000 + 10_000     # bytes, about 10.21 MB


def make(root):
    """Write the test folder. Refuses to write into a folder that is not empty."""
    if os.path.exists(root) and os.listdir(root):
        raise FileExistsError(f"{root} already exists and is not empty; pick a new folder name.")
    os.makedirs(root, exist_ok=True)
    rng = random.Random(42)

    def write(rel, data):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    big = rng.randbytes(5_000_000)
    for d in ("a", "b", "c/deep"):
        write(f"{d}/video_copy.bin", big)

    mid = rng.randbytes(200_000)
    write("a/photo.jpg", mid)
    write("b/photo (1).jpg", mid)

    small = rng.randbytes(10_000)
    write("a/notes.txt", small)
    write("c/notes_backup.txt", small)

    write("a/same_size_1.bin", rng.randbytes(300_000))
    write("b/same_size_2.bin", rng.randbytes(300_000))

    head = rng.randbytes(64 * 1024)
    write("a/same_head_1.bin", head + rng.randbytes(500_000))
    write("b/same_head_2.bin", head + rng.randbytes(500_000))

    for i in range(20):
        write(f"unique/file_{i}.bin", rng.randbytes(1000 + i * 777))

    write("a/empty.txt", b"")
    write("b/empty.txt", b"")
    return os.path.abspath(root)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = argv[0] if argv else "dupe_test"
    try:
        path = make(root)
    except FileExistsError as e:
        sys.exit(str(e))
    print(f"Test data written to {path}")
    print("Expected: 3 duplicate groups, 7 files, about 10.21 MB wasted.")


if __name__ == "__main__":
    main()
