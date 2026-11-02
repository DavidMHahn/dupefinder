"""Organise duplicate groups for review, without touching any file.

People think in folders, not in thousands of single files: "the phone dump
and the archive hold the same photos". So groups are gathered by the set of
folders their copies live in, and those folder sets are listed biggest first.
"""

import os
from dataclasses import dataclass, field


@dataclass
class FolderSet:
    folders: tuple                               # the distinct folders holding the copies, sorted
    groups: list = field(default_factory=list)   # finder.Group objects, most wasted first

    @property
    def wasted(self):
        return sum(g.wasted for g in self.groups)

    @property
    def files(self):
        return sum(len(g.paths) for g in self.groups)

    @property
    def within_one_folder(self):
        """True when every copy is in the same folder (e.g. 'photo (1).jpg')."""
        return len(self.folders) == 1

    def matches(self, text):
        """Case-insensitive search in the folder paths and file names."""
        t = text.lower()
        return (any(t in f.lower() for f in self.folders)
                or any(t in os.path.basename(p).lower() for g in self.groups for p in g.paths))


def folder_sets(groups):
    """Gather groups by the folders their copies are in; biggest saving first."""
    sets = {}
    for g in groups:
        key = tuple(sorted({os.path.dirname(p) for p in g.paths}))
        sets.setdefault(key, FolderSet(key)).groups.append(g)
    for fs in sets.values():
        fs.groups.sort(key=lambda g: g.wasted, reverse=True)
    return sorted(sets.values(), key=lambda fs: (-fs.wasted, fs.folders))

