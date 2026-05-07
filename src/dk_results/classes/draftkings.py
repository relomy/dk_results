# classes/draftkings.py
from __future__ import annotations

import csv
import io
import logging
import os
import pickle
import time
import zipfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from .dksession import DkSession


class Draftkings:
    """
    Thin HTTP client for DraftKings endpoints. Owns an authenticated requests.Session
    created from DkSession unless a session is provided.
    """

    def __init__(
        self,
        *,
        timeout_sec: int = 15,
        cookies_dump_file: Optional[str] = None,
        contest_dir: str = "contests",
        session: Optional[requests.Session] = None,
    ) -> None:
        self.session = session or DkSession().get_session()
        self.timeout_sec = timeout_sec
        self.cookies_dump_file = cookies_dump_file
        self.contest_dir = contest_dir
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _redact_url_for_log(url: str) -> str:
        """Drop querystring/fragment from URLs before logging."""
        if not url:
            return ""
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    # -----------------------
    # Utilities
    # -----------------------

    def clone_auth_to(self, target_session: requests.Session) -> None:
        """
        Copy headers and cookies from this client's session to another Session.
        Use in worker threads to avoid sharing the same Session across threads.
        """
        target_session.headers.update(self.session.headers)
        try:
            target_session.cookies.update(self.session.cookies.get_dict())
        except Exception:
            for c in getattr(self.session, "cookies", []):
                try:
                    target_session.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
                except Exception:
                    pass

    # -----------------------
    # Public HTTP operations
    # -----------------------

    def get_leaderboard(
        self,
        contest_id: int,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ) -> dict[str, Any]:
        """
        Fetch the leaderboard JSON for a contest id.
        """
        to = timeout or self.timeout_sec
        sess = session or self.session
        url = f"https://api.draftkings.com/scores/v1/leaderboards/{contest_id}?format=json&embed=leaderboard"
        r = sess.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

    def get_contest_detail(self, dk_id: int, timeout: Optional[int] = None) -> dict[str, Any]:
        """
        Fetch contest detail JSON for a given contest id.
        """
        to = timeout or self.timeout_sec
        url = f"https://api.draftkings.com/contests/v1/contests/{dk_id}?format=json"
        r = self.session.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

    def get_lobby_contests(
        self, sport: str, *, live: bool = False, timeout: Optional[int] = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Fetch lobby contests listing for a sport. If live=True, hits the live endpoint.
        Returns the decoded JSON (list or dict depending on DK response shape).
        """
        to = timeout or self.timeout_sec
        live_str = "live" if live else ""
        url = f"https://www.draftkings.com/lobby/get{live_str}contests?sport={sport}"
        r = self.session.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

    def get_entry(
        self,
        draft_group: int,
        entry_key: str,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,  # <-- NEW
    ) -> dict[str, Any]:
        """
        Fetch a single entry (scorecard/roster) JSON by draft group and entry key.
        """
        to = timeout or self.timeout_sec
        sess = session or self.session  # <-- NEW
        url = f"https://api.draftkings.com/scores/v2/entries/{draft_group}/{entry_key}?format=json&embed=roster"
        r = sess.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

    def get_contest_entrants_page(
        self,
        contest_id: int,
        page_no: int,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ) -> str:
        """
        Fetch a single entrants page HTML fragment for a contest.
        """
        to = timeout or self.timeout_sec
        sess = session or self.session
        url = f"https://www.draftkings.com/contest/getentrantsmorewithhep?contestId={contest_id}&pageNo={page_no}"
        r = sess.get(url, timeout=to)
        r.raise_for_status()
        return r.text

    def download_contest_rows(
        self,
        contest_id: int,
        *,
        timeout: int = 30,
        cookies_dump_file: Optional[str] = None,
        contest_dir: Optional[str] = None,
    ) -> list[list[str]] | None:
        """
        Download the full standings CSV (possibly as a ZIP) and return parsed rows.
        Returns None if the response is unexpected HTML.
        """
        cdf = cookies_dump_file if cookies_dump_file is not None else self.cookies_dump_file
        cdir = contest_dir if contest_dir is not None else self.contest_dir

        url = f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
        started_at = time.monotonic()
        r = self.session.get(url, timeout=timeout)

        ctype = r.headers.get("Content-Type", "")
        safe_url = self._redact_url_for_log(r.url)
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        self.logger.debug(
            "download_contest_rows contest_id=%s status=%s ctype=%s url=%s elapsed_ms=%d",
            contest_id,
            r.status_code,
            ctype,
            safe_url,
            elapsed_ms,
        )

        if "text/html" in ctype:
            self.logger.warning("Unexpected HTML for contest standings; cannot parse.")
            return None

        # Plain CSV
        if ctype == "text/csv":
            if cdir:
                os.makedirs(cdir, exist_ok=True)
                csv_path = os.path.join(cdir, f"contest-standings-{contest_id}.csv")
                try:
                    with open(csv_path, "wb") as fp:
                        fp.write(r.content)
                    self.logger.debug("wrote standings CSV to %s", csv_path)
                except Exception:
                    self.logger.warning("Failed to write standings CSV to disk.", exc_info=True)
            if cdf:
                try:
                    with open(cdf, "wb") as fp:
                        pickle.dump(self.session.cookies, fp)
                except Exception:
                    self.logger.debug("Skipping cookies dump; non-fatal.", exc_info=True)
            csvfile = r.content.decode("utf-8-sig")
            return list(csv.reader(csvfile.splitlines(), delimiter=","))

        # ZIP containing CSV
        try:
            zip_obj = zipfile.ZipFile(io.BytesIO(r.content))
        except zipfile.BadZipFile:
            self.logger.error("Response was neither CSV nor valid ZIP.")
            return None

        os.makedirs(cdir, exist_ok=True)
        for name in zip_obj.namelist():
            path = zip_obj.extract(name, cdir)
            self.logger.debug("extracted: %s", path)
            with zip_obj.open(name) as csvfile:
                lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
                return list(csv.reader(lines, delimiter=","))

        return None

    def download_salary_csv(self, sport: str, draft_group: int, filename: str) -> None:
        """Given a filename and CSV URL, request download of CSV file and save to filename."""
        contest_types = {
            "GOLF": 9,  # temporary, decide if i want PGA or GOLF
            "MMA": 7,
            "PGA": 9,
            "PGAWeekend": 9,
            "PGAShowdown": 9,
            "SOC": 10,
            "MLB": 12,
            "NFL": 21,
            "NFLAfternoon": 21,
            "NFLShowdown": 21,
            "NAS": 24,
            "NBA": 70,
            "CFB": 94,
            "TEN": 106,
            "LOL": 106,
            "XFL": 134,
            "USFL": 204,
        }

        if sport in contest_types:
            self.logger.debug("CONTEST_TYPES [%s]: %s", sport, contest_types[sport])

        csv_url = (
            "https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={0}&draftGroupId={1}"
        ).format(contest_types[sport], draft_group)

        # send GET request
        response = self.session.get(csv_url)

        # if not successful, raise an exception
        if response.status_code != 200:
            raise Exception("Requests status != 200. It is: {0}".format(response.status_code))

        # dump html to file to avoid multiple requests
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as outfile:
            self.logger.debug("Writing r.text to %s", filename)
            outfile.write(response.text)
