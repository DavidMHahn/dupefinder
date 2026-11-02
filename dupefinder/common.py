"""Helpers shared by the engine modules."""

import hashlib
import os
import sys

PARTIAL_BYTES = 64 * 1024      # stage 3 reads this much from the start of each file
CHUNK_BYTES = 1024 * 1024      # full hashes read files in 1 MB chunks

# Windows system folders on the root of a drive that are not your files.
SKIP_DIRS = {"$recycle.bin", "system volume information"}   # compared lower-case


def fmt(n):
    """Human-readable size: 1234567 -> '1.23 MB'."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:,.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1000


def hash_file(path, limit=None):
    """Return the BLAKE2b hex digest of a file, or of its first `limit` bytes.

    The file is opened with "rb" (read binary), which cannot modify it.
    Returns None if the file cannot be read (locked, removed, bad sector).
    """
    h = hashlib.blake2b(digest_size=32)
    remaining = limit
    try:
        with open(path, "rb") as f:
            while True:
                n = CHUNK_BYTES if remaining is None else min(CHUNK_BYTES, remaining)
                if n == 0:
                    break
                block = f.read(n)
                if not block:
                    break
                h.update(block)
                if remaining is not None:
                    remaining -= len(block)
    except OSError as e:
        print(f"  cannot read {path}: {e}", file=sys.stderr)
        return None
    return h.hexdigest()


def blake2b(path):
    """Full BLAKE2b digest. Unlike hash_file, a read error is raised, not hidden."""
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while block := f.read(CHUNK_BYTES):
            h.update(block)
    return h.hexdigest()


def walk(folder, skip=frozenset(), skip_paths=frozenset()):
    """Yield os.DirEntry for every regular file under folder.

    Symbolic links and Windows junctions are never followed. Folders whose
    lower-case name is in `skip`, or whose lower-case absolute path is in
    `skip_paths`, are left out. Errors are reported and the walk carries on.

    os.scandir is used because on Windows the directory listing already holds
    each file's size, so no extra request to the disk is needed per file.
    """
    stack = [folder]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", bool)():
                            continue                  # don't follow links/junctions
                        if entry.is_dir():
                            if (entry.name.lower() not in skip
                                    and os.path.abspath(entry.path).lower() not in skip_paths):
                                stack.append(entry.path)
                        elif entry.is_file():
                            yield entry
                    except OSError as e:
                        print(f"  skipped {entry.path}: {e}", file=sys.stderr)
        except OSError as e:
            print(f"  cannot open folder {d}: {e}", file=sys.stderr)


def under(path, folders):
    """True if path is inside any of folders (case-insensitive)."""
    p = path.lower()
    return any(p.startswith(f.lower().rstrip("\\/") + os.sep) for f in folders)


def utf8_stdout():
    """Let file names the console can't show print as '?' instead of crashing."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
