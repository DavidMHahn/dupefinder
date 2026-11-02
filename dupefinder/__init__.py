"""dupefinder - find duplicate files and remove them safely.

The engine is split into modules that a command line or a desktop UI can call:

  finder        read-only scan: size, then first 64 KB, then full BLAKE2b hash
  quarantine    move extra copies to a same-drive quarantine (dry run by default), undo
  verify        read-only SAFE / NOT SAFE check of a moves log before deleting
  backup_sets   read-only: files in an old backup set with no copy in the kept sets
  rescue        move those at-risk files out before the old set is removed, undo
  testdata      build a small folder with known duplicates
  store         the SQLite database the app keeps its work in
  review        groups results by the folders that hold the copies
  keepers       decides which copy of each group stays
  dryrun        checks every planned move without moving anything
  mover         carries out a saved dry run (moves to quarantine)
  deleter       permanently deletes a verified, waited-out quarantine

deleter is the only module that deletes files, and only files a moves log
lists as moved into quarantine whose kept copy is still there.
"""

__version__ = "0.2.0"
