"""GitHub Release metadata for the database self-update + version indicator.

The app downloads `eukaryotes.db` from the GitHub Release tagged `latest`
(see `src/constants.DB_DOWNLOAD_URL`). Its tag encodes the build timestamp
(`db-YYYY.MM.DD.HHMM`). Two consumers use this module:

- `src/utils.ensure_latest_database` calls `fetch_latest_release()` on a
  timer (the `ttl` on `cache.get_db_ready`) to notice when a newer weekly
  build has been published and hot-swap the on-disk DB.
- `ui/sidebar.py` renders the *served* DB's build date via `date_from_tag`
  (fed the tag `get_db_ready()` recorded), so the footer reflects the data
  actually loaded rather than merely the latest available.

The fetch is deliberately uncached here: its one caller already runs behind
a cache with its own refresh interval. It fails silent → `None`.
"""

import datetime
import logging

import requests

log = logging.getLogger("euka.db_version")

# GitHub coordinates for the repo the app downloads `eukaryotes.db` from —
# the same `latest` release that `DB_DOWNLOAD_URL` resolves to.
_REPO = "Cobos-Bioinfo/Euka-Survey"
_RELEASE_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_RELEASES_PAGE_URL = f"https://github.com/{_REPO}/releases/latest"
_TIMEOUT_SECONDS = 6
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "EukaSurvey/1.0 (https://github.com/Cobos-Bioinfo/Euka-Survey)",
}


def _format_published(published_at: str | None) -> str | None:
    """Format an ISO-8601 `published_at` (e.g. ``2026-07-01T02:56:24Z``) as
    a friendly ``01 Jul 2026``. Returns `None` if it can't be parsed."""
    if not published_at:
        return None
    try:
        dt = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.strftime("%d %b %Y")


def _release_info_from_json(data: dict) -> dict | None:
    """Build the `{tag, date, url}` dict from a GitHub release JSON payload,
    or `None` if there's no usable date. Pure (no I/O) so it can be
    unit-tested without hitting the network."""
    date = _format_published(data.get("published_at"))
    if date is None:
        return None
    return {
        "tag": data.get("tag_name") or "",
        "date": date,
        "url": data.get("html_url") or _RELEASES_PAGE_URL,
    }


def fetch_latest_release() -> dict | None:
    """Return `{tag, date, url}` for the latest published database release,
    or `None` if the lookup fails. Uncached — the caller controls cadence."""
    try:
        resp = requests.get(_RELEASE_API_URL, headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        log.info("GitHub release lookup failed: %s", e)
        return None
    return _release_info_from_json(data)


def date_from_tag(tag: str | None) -> str | None:
    """Parse a release tag ``db-YYYY.MM.DD.HHMM`` into ``06 Jul 2026``.

    Returns `None` for a missing or unparseable tag (e.g. a user-provided DB
    with no recorded version), so the caller can omit the date.
    """
    if not tag:
        return None
    body = tag[3:] if tag.startswith("db-") else tag
    parts = body.split(".")
    if len(parts) < 3:
        return None
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return datetime.date(year, month, day).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return None


def release_url(tag: str | None) -> str:
    """Link to a specific release tag, or the `latest` page if tag is unknown."""
    if not tag:
        return _RELEASES_PAGE_URL
    return f"https://github.com/{_REPO}/releases/tag/{tag}"
