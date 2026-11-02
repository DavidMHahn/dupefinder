"""Decide which copy of each duplicate group to keep, without touching any file.

The person sets a few rules once (which copy usually wins, which folders to
keep copies in first, which folders copies may be removed from, which file
names never move), and can pick the keeper of any single group by hand. This
module turns those choices into a plan: for every group, the one copy that
stays and the copies that the Dry run step would move to quarantine.

Nothing here moves or deletes a file. Only "oldest"/"newest" read file dates.
"""

import fnmatch
import os
from dataclasses import asdict, dataclass, field

from .common import under

RULES = {
    "shortest": "Shortest path (usually the original location)",
    "oldest": "Oldest modified date",
    "newest": "Newest modified date",
    "alpha": "First alphabetically",
}

# Small files that belong in each folder; moving them only breaks things.
DEFAULT_SKIP_NAMES = ["desktop.ini", "Thumbs.db", "Folder.jpg", "AlbumArt*", ".DS_Store"]

KEEP, MOVE, STAYS_FOLDER, STAYS_NAME = "keep", "move", "stays: outside the folders to clean", "stays: name rule"


@dataclass
class Rules:
    keep: str = "shortest"
    prefer: list = field(default_factory=list)       # keep copies here first, in this order
    only_from: list = field(default_factory=list)    # if set, only remove copies from these folders
    skip_names: list = field(default_factory=lambda: list(DEFAULT_SKIP_NAMES))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        r = cls()
        for k in ("keep", "prefer", "only_from", "skip_names"):
            if k in (d or {}):
                setattr(r, k, d[k])
        if r.keep not in RULES:
            r.keep = "shortest"
        return r


@dataclass
class GroupPlan:
    number: int                 # the group's number in the scan (1 = most wasted space)
    size: int
    status: dict                # path -> KEEP, MOVE or a "stays: ..." reason
    by_hand: bool = False       # keeper picked by the person, not by the rules

    @property
    def keeper(self):
        return next((p for p, s in self.status.items() if s == KEEP), None)

    @property
    def moves(self):
        return [p for p, s in self.status.items() if s == MOVE]

    @property
    def freed(self):
        return self.size * len(self.moves)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def skipped_name(path, patterns):
    name = os.path.basename(path).lower()
    return any(fnmatch.fnmatch(name, pat.lower()) for pat in patterns)


def pick_keeper(paths, rules):
    """The rules' choice among paths. Ties fall back to alphabetical order."""
    paths = sorted(paths)
    for folder in rules.prefer:                  # first listed folder that holds a copy wins
        inside = [p for p in paths if under(p, [folder])]
        if inside:
            paths = inside
            break
    if rules.keep in ("oldest", "newest"):
        dated = [(t, p) for p in paths if (t := _mtime(p)) is not None]
        if dated:
            sign = 1 if rules.keep == "oldest" else -1
            return min(dated, key=lambda tp: (sign * tp[0], tp[1]))[1]
    if rules.keep == "shortest":
        return min(paths, key=lambda p: (p.count(os.sep), len(p), p))
    return paths[0]


def plan_group(number, group, rules, by_hand=None):
    """Plan one group. by_hand is a path the person chose to keep, or None."""
    status = {}
    eligible = []
    for p in sorted(group.paths):
        if skipped_name(p, rules.skip_names):
            status[p] = STAYS_NAME
        else:
            eligible.append(p)
    if len(eligible) < 2:                        # name rules leave nothing to de-duplicate
        for p in eligible:
            status[p] = KEEP
        return GroupPlan(number, group.size, {p: status[p] for p in sorted(group.paths)})

    hand = by_hand if by_hand in eligible else None
    if hand:
        keeper = hand
    else:
        outside = [p for p in eligible if not under(p, rules.only_from)] if rules.only_from else []
        keeper = pick_keeper(outside or eligible, rules)
    for p in eligible:
        if p == keeper:
            status[p] = KEEP
        elif rules.only_from and not under(p, rules.only_from):
            status[p] = STAYS_FOLDER
        else:
            status[p] = MOVE
    return GroupPlan(number, group.size, {p: status[p] for p in sorted(group.paths)}, bool(hand))


def plan(groups, rules, by_hand=None):
    """Plan every group. groups are in scan order; by_hand maps group number -> path."""
    by_hand = by_hand or {}
    return [plan_group(i, g, rules, by_hand.get(i)) for i, g in enumerate(groups, 1)]


@dataclass
class Totals:
    groups: int = 0
    acting: int = 0             # groups where at least one copy would move
    moves: int = 0
    freed: int = 0
    by_hand: int = 0
    stays: int = 0              # extra copies that stay because of a folder or name rule


def totals(plans):
    t = Totals(groups=len(plans))
    for gp in plans:
        n = len(gp.moves)
        t.moves += n
        t.freed += gp.freed
        t.acting += n > 0
        t.by_hand += gp.by_hand
        t.stays += sum(1 for s in gp.status.values() if s.startswith("stays"))
    return t
