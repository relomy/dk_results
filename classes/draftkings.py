# classes/draftkings.py
from __future__ import annotations

import csv
import io
import logging
import os
import pickle
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from .dksession import DkSession

logger = logging.getLogger(__name__)


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
        self.logger = logging.getLogger(self.__class__.__name__)

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
                    target_session.cookies.set(
                        c.name, c.value, domain=c.domain, path=c.path
                    )
                except Exception:
                    pass

    # -----------------------
    # Public HTTP operations
    # -----------------------

    def get_leaderboard(
        self,
        dk_id: int,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,  # <-- NEW
    ) -> dict:
        """
        Fetch the leaderboard JSON for a contest id (dk_id).
        """
        to = timeout or self.timeout_sec
        sess = session or self.session  # <-- NEW
        url = (
            f"https://api.draftkings.com/scores/v1/leaderboards/"
            f"{dk_id}?format=json&embed=leaderboard"
        )
        r = sess.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

    def get_contest_detail(self, dk_id: int, timeout: Optional[int] = None) -> dict:
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
    ) -> dict | list:
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

    # -----------------------
    # VIP Lineups helper
    # -----------------------

    def _fetch_user_lineup_worker(self, user_dict: dict, dg: int) -> dict | None:
        entry_key = user_dict.get("entryKey")
        if not entry_key:
            return None

        # Use a thread-local session for safety
        thread_sess = requests.Session()
        self.clone_auth_to(thread_sess)

        scorecard_js = self.get_entry(
            dg, entry_key, timeout=self.timeout_sec, session=thread_sess
        )

        entries = scorecard_js.get("entries", [])
        if not entries:
            return None
        roster = entries[0].get("roster", {})
        scorecards = roster.get("scorecards", [])
        players = []
        for sc in scorecards:
            projection = sc.get("projection", {}) or {}
            percent = sc.get("percentDrafted")
            ownership = float(percent) / 100 if percent not in (None, "") else ""
            players.append(
                {
                    "pos": sc.get("rosterPosition", "") or "",
                    "name": sc.get("displayName", "") or "",
                    "ownership": ownership,
                    "pts": str(sc.get("score", "") or ""),
                    "rtProj": str(projection.get("realTimeProjection", "") or ""),
                    "timeStatus": str(sc.get("timeRemaining", "") or ""),
                    "stats": sc.get("statsDescription", "") or "",
                    "valueIcon": projection.get("valueIcon", "") or "",
                }
            )

        return {
            "user": user_dict.get("userName", ""),
            "pmr": user_dict.get("timeRemaining", ""),
            "rank": user_dict.get("rank", ""),
            "pts": user_dict.get("fantasyPoints", ""),
            "players": players,
        }

    def get_vip_lineups(
        self, dk_id: int, dg: int, vips: list[str], max_workers: int = 8
    ) -> list[dict]:
        """
        Fetch VIP lineups concurrently and format for sheet usage.
        Returns list of dicts with user metadata and players.
        """
        js_leaderboard = self.get_leaderboard(dk_id, timeout=self.timeout_sec)
        found_users = [
            u
            for u in js_leaderboard.get("leaderBoard", [])
            if u.get("userName") in vips
        ]
        if not found_users:
            return []

        max_workers = min(max_workers, len(found_users)) or 1
        vip_lineups: list[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._fetch_user_lineup_worker, u, dg): u
                for u in found_users
            }
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    if result:
                        vip_lineups.append(result)
                except Exception:
                    # Best-effort logging at client level
                    try:
                        logger.exception(
                            "Failed fetching lineup for %s",
                            futures[fut].get("userName"),
                        )
                    except Exception:
                        pass
        return vip_lineups

    def get_entry(
        self,
        draft_group: int,
        entry_key: str,
        timeout: Optional[int] = None,
        session: Optional[requests.Session] = None,  # <-- NEW
    ) -> dict:
        """
        Fetch a single entry (scorecard/roster) JSON by draft group and entry key.
        """
        to = timeout or self.timeout_sec
        sess = session or self.session  # <-- NEW
        url = (
            f"https://api.draftkings.com/scores/v2/entries/"
            f"{draft_group}/{entry_key}?format=json&embed=roster"
        )
        r = sess.get(url, timeout=to)
        r.raise_for_status()
        return r.json()

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
        cdf = (
            cookies_dump_file
            if cookies_dump_file is not None
            else self.cookies_dump_file
        )
        cdir = contest_dir if contest_dir is not None else self.contest_dir

        url = f"https://www.draftkings.com/contest/exportfullstandingscsv/{contest_id}"
        r = self.session.get(url, timeout=timeout)

        ctype = r.headers.get("Content-Type", "")
        logger.debug(
            "download_contest_rows status=%s url=%s ctype=%s",
            r.status_code,
            r.url,
            ctype,
        )

        if "text/html" in ctype:
            logger.warning("Unexpected HTML for contest standings; cannot parse.")
            return None

        # Plain CSV
        if ctype == "text/csv":
            if cdf:
                try:
                    with open(cdf, "wb") as fp:
                        pickle.dump(self.session.cookies, fp)
                except Exception:
                    logger.debug("Skipping cookies dump; non-fatal.", exc_info=True)
            csvfile = r.content.decode("utf-8-sig")
            return list(csv.reader(csvfile.splitlines(), delimiter=","))

        # ZIP containing CSV
        try:
            zip_obj = zipfile.ZipFile(io.BytesIO(r.content))
        except zipfile.BadZipFile:
            logger.error("Response was neither CSV nor valid ZIP.")
            return None

        os.makedirs(cdir, exist_ok=True)
        for name in zip_obj.namelist():
            path = zip_obj.extract(name, cdir)
            logger.debug("extracted: %s", path)
            with zip_obj.open(name) as csvfile:
                lines = io.TextIOWrapper(csvfile, encoding="utf-8", newline="\n")
                return list(csv.reader(lines, delimiter=","))

        return None

    def download_salary_csv(self, sport, draft_group, filename):
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
            "https://www.draftkings.com/lineup/getavailableplayerscsv?"
            "contestTypeId={0}&draftGroupId={1}"
        ).format(contest_types[sport], draft_group)

        # send GET request
        response = self.session.get(csv_url)

        # if not successful, raise an exception
        if response.status_code != 200:
            raise Exception(
                "Requests status != 200. It is: {0}".format(response.status_code)
            )

        # dump html to file to avoid multiple requests
        with open(filename, "w") as outfile:
            self.logger.debug("Writing r.text to %s", filename)
            print(response.text, file=outfile)
