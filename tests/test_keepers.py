import os
import time

from dupefinder.finder import Group
from dupefinder.keepers import KEEP, STAYS_FOLDER, STAYS_NAME, Rules, plan, plan_group, totals
from dupefinder.store import Store


def p(*parts):
    return os.path.join(os.path.abspath(os.sep), *parts)


def test_default_rule_keeps_shortest_path_and_moves_the_rest():
    g = Group(100, [p("Backup", "old", "a.jpg"), p("Photos", "a.jpg"), p("Phone", "DCIM", "a.jpg")], "h")
    gp = plan_group(1, g, Rules())
    assert gp.keeper == p("Photos", "a.jpg")
    assert sorted(gp.moves) == [p("Backup", "old", "a.jpg"), p("Phone", "DCIM", "a.jpg")]
    assert gp.freed == 200 and not gp.by_hand


def test_preferred_folders_win_in_the_order_listed():
    g = Group(1, [p("A", "x"), p("B", "deep", "x"), p("C", "deep", "x")], "h")
    assert plan_group(1, g, Rules(prefer=[p("C"), p("B")])).keeper == p("C", "deep", "x")
    assert plan_group(1, g, Rules(prefer=[p("Z"), p("B")])).keeper == p("B", "deep", "x")
    # a folder whose name only starts the same is not "inside"
    assert plan_group(1, g, Rules(prefer=[p("B", "dee")])).keeper == p("A", "x")


def test_only_remove_from_some_folders():
    g = Group(10, [p("Arc", "x"), p("Dump", "x"), p("Dump", "copy", "x"), p("Other", "x")], "h")
    gp = plan_group(1, g, Rules(only_from=[p("Dump")]))
    assert gp.keeper == p("Arc", "x")                       # kept outside the folder to clean
    assert sorted(gp.moves) == [p("Dump", "copy", "x"), p("Dump", "x")]
    assert gp.status[p("Other", "x")] == STAYS_FOLDER


def test_all_copies_in_the_folder_to_clean_still_keeps_one():
    g = Group(10, [p("Dump", "x"), p("Dump", "y", "x")], "h")
    gp = plan_group(1, g, Rules(only_from=[p("Dump")]))
    assert gp.keeper == p("Dump", "x") and gp.moves == [p("Dump", "y", "x")]


def test_names_that_never_move():
    g = Group(5, [p("A", "Folder.jpg"), p("B", "folder.JPG")], "h")
    gp = plan_group(1, g, Rules())                              # defaults include Folder.jpg
    assert gp.moves == [] and set(gp.status.values()) == {STAYS_NAME}
    g = Group(5, [p("A", "albumart_1.jpg"), p("B", "x.jpg"), p("C", "x.jpg")], "h")
    gp = plan_group(1, g, Rules())
    assert gp.status[p("A", "albumart_1.jpg")] == STAYS_NAME and len(gp.moves) == 1


def test_oldest_and_newest(tmp_path):
    old, new = tmp_path / "old.bin", tmp_path / "zz" / "new.bin"
    new.parent.mkdir()
    for f in (old, new):
        f.write_bytes(b"x")
    t = time.time()
    os.utime(old, (t - 1000, t - 1000))
    os.utime(new, (t, t))
    g = Group(1, [str(new), str(old), str(tmp_path / "gone.bin")], "h")    # one copy missing
    assert plan_group(1, g, Rules(keep="oldest")).keeper == str(old)
    assert plan_group(1, g, Rules(keep="newest")).keeper == str(new)


def test_pick_by_hand_overrides_rules_and_bad_picks_are_ignored():
    groups = [Group(1, [p("A", "x"), p("B", "x")], "h1"), Group(2, [p("A", "y"), p("B", "y")], "h2")]
    plans = plan(groups, Rules(), {1: p("B", "x"), 2: p("Gone", "y")})
    assert plans[0].keeper == p("B", "x") and plans[0].by_hand
    assert plans[1].keeper == p("A", "y") and not plans[1].by_hand
    t = totals(plans)
    assert (t.groups, t.moves, t.freed, t.by_hand, t.acting) == (2, 2, 3, 1, 2)


def test_every_group_keeps_exactly_one_copy():
    groups = [Group(i + 1, [p(d, f"f{i}") for d in "ABCD"[: 2 + i % 3]], str(i)) for i in range(30)]
    for rules in (Rules(), Rules(keep="alpha", prefer=[p("C")]), Rules(only_from=[p("A"), p("D")])):
        for gp in plan(groups, rules):
            assert list(gp.status.values()).count(KEEP) == 1
            assert gp.keeper not in gp.moves


def test_rules_round_trip_and_bad_values():
    r = Rules(keep="newest", prefer=["x"], only_from=["y"], skip_names=["*.ini"])
    assert Rules.from_dict(r.to_dict()) == r
    assert Rules.from_dict({"keep": "nonsense"}).keep == "shortest"
    assert Rules.from_dict(None) == Rules()


def test_choices_saved_per_scan(tmp_path):
    from dupefinder.finder import ScanResult
    with Store(str(tmp_path / "d.db")) as st:
        res = ScanResult(groups=[Group(1, ["a", "b"], "h")])
        s1 = st.save_scan(["r"], {}, res, "2026-11-02 12:00:00")
        s2 = st.save_scan(["r"], {}, res, "2026-11-02 12:05:00")
        assert st.load_choices(s1) == (None, {})
        st.save_choices(s1, Rules(keep="oldest").to_dict(), {1: "b"})
        st.save_choices(s1, Rules(keep="alpha").to_dict(), {1: "a"})        # replaces
        rules, picks = st.load_choices(s1)
        assert rules["keep"] == "alpha" and picks == {1: "a"}
        assert st.load_choices(s2) == (None, {})

