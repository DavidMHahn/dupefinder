import os

from dupefinder.finder import Group
from dupefinder.review import folder_sets


def p(*parts):
    return os.path.join(os.path.abspath(os.sep), *parts)


def test_groups_gathered_by_folders_biggest_first():
    groups = [
        Group(10, [p("Archive", "a.jpg"), p("Phone", "a.jpg")], "h1"),
        Group(500, [p("Archive", "v.mp4"), p("Phone", "v.mp4")], "h2"),
        Group(1000, [p("Music", "x.mp3"), p("Music", "x (1).mp3")], "h3"),
        Group(5, [p("A", "n.txt"), p("B", "n.txt"), p("C", "n.txt")], "h4"),
    ]
    sets = folder_sets(groups)
    assert [s.wasted for s in sets] == [1000, 510, 10]
    music, pair, three = sets
    assert music.within_one_folder and music.folders == (p("Music"),)
    assert pair.folders == (p("Archive"), p("Phone"))
    assert [g.digest for g in pair.groups] == ["h2", "h1"]          # biggest group first
    assert pair.files == 4
    assert len(three.folders) == 3


def test_filter_matches_folders_and_file_names():
    fs = folder_sets([Group(1, [p("Photos", "Trip.JPG"), p("Backup", "Trip.JPG")], "h")])[0]
    assert fs.matches("photos") and fs.matches("trip.jpg") and not fs.matches("music")


def test_no_groups():
    assert folder_sets([]) == []
