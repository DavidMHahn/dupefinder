import pytest

from dupefinder import testdata


def test_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "x").write_bytes(b"1")
    with pytest.raises(FileExistsError):
        testdata.make(str(tmp_path))


def test_same_data_every_time(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    testdata.make(str(a))
    testdata.make(str(b))
    assert (a / "a" / "video_copy.bin").read_bytes() == (b / "a" / "video_copy.bin").read_bytes()
