"""dupefinder - find duplicate files and remove them safely.

The engine is split into modules that a command line or a desktop UI can call:

  finder        read-only scan: size, then first 64 KB, then full BLAKE2b hash
  quarantine    move extra copies to a same-drive quarantine (dry run by default), undo
  verify        read-only SAFE / NOT SAFE check of a moves log before deleting
  backup_sets   read-only: files in an old backup set with no copy in the kept sets
  rescue        move those at-risk files out before the old set is removed, undo
  testdata      build a small folder with known duplicates

Nothing in the engine deletes a file.
"""

__version__ = "0.1.0"
