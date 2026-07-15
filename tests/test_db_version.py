"""Unit tests for the pure (no-I/O) helpers in `src.db_version`.

The network fetch `fetch_latest_release` isn't exercised here — the JSON→dict
shaping, publish-date formatting, and release-tag parsing it and the sidebar
rely on live in the pure helpers below, so those are what we guard.
"""

from src import db_version


def test_format_published_iso_z():
    assert db_version._format_published("2026-07-01T02:56:24Z") == "01 Jul 2026"


def test_format_published_handles_none_and_garbage():
    assert db_version._format_published(None) is None
    assert db_version._format_published("") is None
    assert db_version._format_published("not-a-date") is None


def test_release_info_from_json_happy_path():
    data = {
        "tag_name": "db-2026.07.01.0256",
        "published_at": "2026-07-01T02:56:24Z",
        "html_url": "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/tag/db-2026.07.01.0256",
    }
    assert db_version._release_info_from_json(data) == {
        "tag": "db-2026.07.01.0256",
        "date": "01 Jul 2026",
        "url": "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/tag/db-2026.07.01.0256",
    }


def test_release_info_from_json_missing_date_is_none():
    # No usable date → no indicator.
    assert db_version._release_info_from_json({"tag_name": "db-x"}) is None


def test_release_info_from_json_falls_back_to_releases_page():
    info = db_version._release_info_from_json({"published_at": "2026-07-01T02:56:24Z"})
    assert info is not None
    assert info["tag"] == ""
    assert info["url"] == db_version._RELEASES_PAGE_URL


def test_date_from_tag_parses_build_tag():
    assert db_version.date_from_tag("db-2026.07.06.0320") == "06 Jul 2026"
    # Tolerates a tag without the `db-` prefix.
    assert db_version.date_from_tag("2026.12.25.0000") == "25 Dec 2026"


def test_date_from_tag_handles_missing_or_malformed():
    assert db_version.date_from_tag(None) is None
    assert db_version.date_from_tag("") is None
    assert db_version.date_from_tag("db-2026.07") is None      # too few fields
    assert db_version.date_from_tag("db-nope.xx.yy.zz") is None  # non-numeric
    assert db_version.date_from_tag("db-2026.13.40.0000") is None  # out-of-range date


def test_release_url_builds_tag_url_or_falls_back():
    assert (
        db_version.release_url("db-2026.07.06.0320")
        == "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/tag/db-2026.07.06.0320"
    )
    assert db_version.release_url(None) == db_version._RELEASES_PAGE_URL
