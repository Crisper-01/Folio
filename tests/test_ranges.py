import pytest

from folio.ranges import RangeError, flat_pages, format_size, parse_ranges


def test_parse_ranges():
    assert parse_ranges("1-3, 5, 7-", 8) == [[0, 1, 2], [4], [6, 7]]
    assert parse_ranges("3-1", 3) == [[2, 1, 0]]
    assert flat_pages("1-2,2,3", 3) == [0, 1, 2]
    for bad in ("", "a", "0", "9", "2-12"):
        with pytest.raises(RangeError):
            parse_ranges(bad, 8)


def test_format_size():
    assert format_size(512) == "512 o"
    assert format_size(2_500_000) == "2,4 Mo"
