# classes/draftkings.py
from __future__ import annotations

import csv
import io
import logging
import os
import pickle
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

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
    ) -> dict[str, Any]:
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

    def get_contest_detail(
        self, dk_id: int, timeout: Optional[int] = None
    ) -> dict[str, Any]:
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

    # -----------------------
    # VIP Lineups helper
    # -----------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            return ""
        return "".join(
            c
            for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

    def _lookup_salary(
        self, player_name: str, player_salary_map: dict[str, int] | None
    ) -> int | None:
        if not player_salary_map or not player_name:
            return None
        clean_name = player_name.strip()
        if not clean_name:
            return None
        if clean_name in player_salary_map:
            return player_salary_map[clean_name]
        normalized = self._normalize_name(clean_name)
        if normalized in player_salary_map:
            return player_salary_map[normalized]
        return None

    def _fetch_user_lineup_worker(
        self,
        user_dict: dict[str, Any],
        dg: int,
        player_salary_map: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
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
        players: list[dict[str, Any]] = []
        total_salary = 0
        for sc in scorecards:
            projection = sc.get("projection", {}) or {}
            percent = sc.get("percentDrafted")
            ownership = float(percent) / 100 if percent not in (None, "") else ""
            display_name = sc.get("displayName", "") or "LOCKED 🔒"
            salary_val = self._lookup_salary(display_name, player_salary_map)
            salary_display = str(salary_val) if salary_val is not None else ""
            if salary_val is not None:
                total_salary += salary_val
            pts_raw = sc.get("score", "") or ""
            pts_display = str(pts_raw)
            value = ""
            if salary_val is not None:
                try:
                    pts_val = float(pts_raw)
                    if pts_val:
                        value = f"{pts_val / (salary_val / 1000):.2f}"
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            rt_proj_raw = projection.get("realTimeProjection", "")
            rt_proj = ""
            if rt_proj_raw not in (None, ""):
                try:
                    rt_proj = f"{float(rt_proj_raw):.2f}"
                except (TypeError, ValueError):
                    rt_proj = str(rt_proj_raw)

            players.append(
                {
                    "pos": sc.get("rosterPosition", "") or "",
                    "name": display_name,
                    "ownership": ownership,
                    "pts": pts_display,
                    "rtProj": rt_proj,
                    "timeStatus": str(sc.get("timeRemaining", "") or ""),
                    "stats": sc.get("statsDescription", "") or "",
                    "valueIcon": projection.get("valueIcon", "") or "",
                    "salary": salary_display,
                    "value": value,
                }
            )

        return {
            "user": user_dict.get("userName", ""),
            "pmr": user_dict.get("timeRemaining", ""),
            "rank": user_dict.get("rank", ""),
            "pts": user_dict.get("fantasyPoints", ""),
            "salary": total_salary,
            "players": players,
        }

    def get_vip_lineups(
        self,
        dk_id: int,
        dg: int,
        vips: list[str],
        vip_entries: dict[str, dict[str, Any] | str] | None = None,
        player_salary_map: dict[str, int] | None = None,
        max_workers: int = 8,
    ) -> list[dict[str, Any]]:
        """
        Fetch VIP lineups concurrently and format for sheet usage.
        If vip_entries are provided (mapping user -> entry_key), those entries
        are fetched directly; otherwise the leaderboard is queried and filtered
        by the provided vips list. Returns list of dicts with user metadata and players.
        When player_salary_map is provided (name -> salary), the lineup rows include
        a salary/points value derived from that data.
        """
        users_to_fetch: list[dict[str, Any]] = []
        if vip_entries:
            for vip_name, entry_data in vip_entries.items():
                if isinstance(entry_data, dict):
                    entry_key = entry_data.get("entry_key") or entry_data.get(
                        "entryKey"
                    )
                    pmr = entry_data.get("pmr", "")
                    rank = entry_data.get("rank", "")
                    fantasy_points = entry_data.get("pts", "")
                else:
                    entry_key = entry_data
                    pmr = rank = fantasy_points = ""
                if not entry_key:
                    continue

                users_to_fetch.append(
                    {
                        "userName": vip_name,
                        "entryKey": entry_key,
                        "timeRemaining": pmr,
                        "rank": rank,
                        "fantasyPoints": fantasy_points,
                    }
                )
        else:
            js_leaderboard = self.get_leaderboard(dk_id, timeout=self.timeout_sec)
            users_to_fetch = [
                u
                for u in js_leaderboard.get("leaderBoard", [])
                if u.get("userName") in vips
            ]

        if not users_to_fetch:
            self.logger.debug("No VIP entries found to fetch.")
            return []

        max_workers = min(max_workers, len(users_to_fetch)) or 1
        vip_lineups: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._fetch_user_lineup_worker, u, dg, player_salary_map
                ): u
                for u in users_to_fetch
            }
            for fut in as_completed(futures):
                user = futures[fut].get("userName", "<unknown>")
                try:
                    result = fut.result()

                    if not result:
                        self.logger.debug("VIP %s had no roster data", user)
                        continue

                    self.logger.info(
                        "Found VIP lineup for user %s", result.get("user", user)
                    )
                    vip_lineups.append(result)
                except Exception as e:
                    # Best-effort logging at client level
                    try:
                        self.logger.error(
                            "Failed fetching lineup for %s: %s",
                            user,
                            e,
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
    ) -> dict[str, Any]:
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
        self.logger.debug(
            "download_contest_rows status=%s url=%s ctype=%s",
            r.status_code,
            r.url,
            ctype,
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
                    self.logger.warning(
                        "Failed to write standings CSV to disk.", exc_info=True
                    )
            if cdf:
                try:
                    with open(cdf, "wb") as fp:
                        pickle.dump(self.session.cookies, fp)
                except Exception:
                    self.logger.debug(
                        "Skipping cookies dump; non-fatal.", exc_info=True
                    )
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
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as outfile:
            self.logger.debug("Writing r.text to %s", filename)
            outfile.write(response.text)
