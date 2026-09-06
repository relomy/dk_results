"""
Find contests for a sport and print cron job.

URL: https://www.draftkings.com/lobby/getcontests?sport=NBA
Response format: {
    'SelectedSport': 4,
    # To find the correct contests, see: find_new_contests()
    'Contests': [{
        'id': '16911618',                              # Contest id
        'n': 'NBA $375K Tipoff Special [$50K to 1st]', # Contest name
        'po': 375000,                                  # Total payout
        'm': 143750,                                   # Max entries
        'a': 3.0,                                      # Entry fee
        'sd': '/Date(1449619200000)/'                  # Start date
        'dg': 8014                                     # Draft group
        ... (the rest is unimportant)
    },
    ...
    ],
    # Draft groups are for querying salaries, see: run()
    'DraftGroups': [{
        'DraftGroupId': 8014,
        'ContestTypeId': 5,
        'StartDate': '2015-12-09T00:00:00.0000000Z',
        'StartDateEst': '2015-12-08T19:00:00.0000000',
        'Sport': 'NBA',
        'GameCount': 6,
        'ContestStartTimeSuffix': null,
        'ContestStartTimeType': 0,
        'Games': null
    },
    ...
    ],
    ... (the rest is unimportant)
}
"""

import argparse
import datetime
from collections.abc import Mapping
from typing import Type

from dfs_common import state

from dk_results.domain.contest import Contest
from dk_results.domain.sport import Sport, get_sport_choices
from dk_results.lobby.common import valid_date
from dk_results.lobby.contest_filter import filter_double_ups, is_double_up_contest, largest_by_entries
from dk_results.lobby.double_ups import get_stats
from dk_results.lobby.draft_group_filter import filter_draft_groups
from dk_results.lobby.fetch import get_lobby_response
from dk_results.lobby.parsing import get_contests_from_response
from dk_results.persistence.contestdatabase import ContestDatabase


def get_contests(sport: str, live: bool = False):
    response = get_lobby_response(sport, live=live)
    return get_contests_from_response(response)


def get_sport_class_choices() -> Mapping[str, Type[Sport]]:
    return get_sport_choices()


def format_sport_class_game_type_help(
    choices: Mapping[str, Type[Sport]],
) -> str:
    lines = ["Sport-class gameTypeId constraints:"]
    constrained = [
        (name, sport_cls.contest_restraint_game_type_id)
        for name, sport_cls in sorted(choices.items())
        if sport_cls.contest_restraint_game_type_id is not None
    ]
    if not constrained:
        lines.append("  (none configured)")
    else:
        for name, game_type_id in constrained:
            lines.append(f"  {name}: {game_type_id}")
    return "\n".join(lines)


def get_contests_for_sport_class(
    sport_class: str,
    choices: Mapping[str, Type[Sport]] | None = None,
) -> list[dict]:
    choices = choices or get_sport_class_choices()
    if sport_class not in choices:
        raise ValueError(f"Unknown sport class: {sport_class}")
    sport_obj = choices[sport_class]
    response = get_lobby_response(sport_obj.get_primary_sport(), live=False)
    if not isinstance(response, dict):
        raise SystemExit("Sport-class mode requires getcontests response with DraftGroups.")
    contests = get_contests_from_response(response)
    draft_groups = set(filter_draft_groups(response["DraftGroups"], sport_obj))
    return [contest for contest in contests if contest.get("dg") in draft_groups]


def get_draft_group_info(
    response: dict | list[dict],
    draft_group_id: int,
) -> dict | None:
    if not isinstance(response, dict) or "DraftGroups" not in response:
        return None
    for draft_group in response["DraftGroups"]:
        if draft_group.get("DraftGroupId") == draft_group_id:
            return draft_group
    return None


def get_largest_contest(
    contests,
    dt,
    entry_fee=25,
    query=None,
    exclude=None,
    game_type_id: int | None = None,
):
    """Return the largest (by entries) double-up contest matching criteria, or None.

    Parameters
    ----------
    contests : list of Contest
        Lobby contests to search.
    dt : datetime.datetime
        Only contests starting on this date are considered.
    entry_fee : int, optional
        Exact entry fee to match, by default 25.
    query : str, optional
        Substring that must appear in the contest name.
    exclude : str, optional
        Substring that must not appear in the contest name.
    game_type_id : int, optional
        DraftKings game type ID constraint.
    """
    print("contests size: {}".format(len(contests)))
    matched = filter_double_ups(
        contests,
        min_entry_fee=entry_fee,
        max_entry_fee=entry_fee,
        start_date=dt.date(),
        game_type_id=game_type_id,
        name_contains=query,
        name_excludes=exclude,
    )
    print("number of contests meeting requirements: {}".format(len(matched)))
    if not matched and (query is not None or exclude is not None):
        print_eliminated_candidates(contests, dt, entry_fee, game_type_id)
    return largest_by_entries(matched)


def print_eliminated_candidates(contests, dt, entry_fee, game_type_id: int | None) -> None:
    """Print the double-up(s) at ``entry_fee`` that a query/exclude filter eliminated."""
    candidates = filter_double_ups(
        contests,
        min_entry_fee=entry_fee,
        max_entry_fee=entry_fee,
        start_date=dt.date(),
        game_type_id=game_type_id,
    )
    if not candidates:
        return
    names = ", ".join(repr(c.name) for c in candidates)
    print(f"  query/exclude matched none of the ${entry_fee} double-up(s): {names}")


def get_available_dub_fees(contests, dt: datetime.datetime) -> list:
    """Distinct entry fees with at least one single-entry double-up on ``dt``, descending."""
    fees = {c.entry_fee for c in contests if is_double_up_contest(c) and c.start_dt.date() == dt.date()}
    return sorted(fees, reverse=True)


def get_largest_contest_with_fallback(
    contests,
    dt,
    entry_fee=25,
    query=None,
    exclude=None,
    game_type_id: int | None = None,
):
    """Try ``entry_fee``, then fall back to the next lower double-up fee tier present that day."""
    lower_tiers = [fee for fee in get_available_dub_fees(contests, dt) if fee < entry_fee]
    for fee in [entry_fee, *lower_tiers]:
        contest = get_largest_contest(contests, dt, fee, query, exclude, game_type_id=game_type_id)
        if contest:
            if fee != entry_fee:
                print(f"No ${entry_fee} match; falling back to ${fee}.")
            return contest
    return None


def get_contests_by_entries(contests, entry_fee, limit):
    return sorted(
        [c for c in contests if c.entry_fee == entry_fee and c.entries > limit],
        key=lambda x: x.entries,
        reverse=True,
    )


def print_sql_insert(contest):
    def _sql_literal(value):
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"

    fields = [
        "sport",
        "dk_id",
        "name",
        "start_date",
        "draft_group",
        "total_prizes",
        "entries",
        "positions_paid",
        "entry_fee",
        "entry_count",
        "max_entry_count",
    ]
    values = [
        contest.sport,
        contest.id,
        contest.name,
        contest.start_dt,
        contest.draft_group,
        contest.total_prizes,
        contest.entries,
        None,
        contest.entry_fee,
        contest.entry_count,
        contest.max_entry_count,
    ]
    value_str = ", ".join(_sql_literal(v) for v in values)
    print(f"INSERT INTO contests ({', '.join(fields)}) VALUES ({value_str})")


def confirm_insert() -> bool:
    """Prompt for confirmation before inserting a contest. Defaults to no."""
    answer = input("Insert this contest into contests.db? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def maybe_insert_contest(contest: Contest, insert: bool) -> None:
    """Insert ``contest`` into the contests DB if requested and confirmed."""
    if not insert or not confirm_insert():
        return
    db = ContestDatabase(str(state.contests_db_path()))
    try:
        db.create_table()
        new_ids = db.compare_contests([contest])
        db.insert_contests([contest])
        if new_ids:
            print(f"Inserted contest {contest.id} into contests.db.")
        else:
            print(f"Contest {contest.id} already exists in contests.db; no change made.")
    finally:
        db.close()


def print_stats(contests):
    stats = get_stats(contests, include_largest=True)

    if stats:
        print("Breakdown per date:")
        for date, values in sorted(stats.items()):
            print(f"{date} - {values['count']} total contests")

            if "dubs" in values:
                print("Single-entry double ups:")
                for entry_fee, inner_dict in sorted(values["dubs"].items()):
                    # inner_dict has 'count' and 'largest' keys
                    print(
                        f"     ${entry_fee}: {inner_dict['count']} contest(s) "
                        f"(largest entry count: {inner_dict['largest']})"
                    )


def main():
    """"""

    supported_sports = [
        "NBA",
        "NFL",
        "CFB",
        "GOLF",
        "NHL",
        "MLB",
        "SOC",
        "TEN",
        "XFL",
        "MMA",
        "LOL",
        "NAS",
        "USFL",
    ]

    sport_class_choices = get_sport_class_choices()
    sport_class_help = format_sport_class_game_type_help(sport_class_choices)

    # parse arguments
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=sport_class_help,
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "-s",
        "--sport",
        choices=supported_sports,
        help="Legacy sport code (existing behavior).",
    )
    mode_group.add_argument(
        "--sport-class",
        choices=sorted(sport_class_choices),
        help="Use standard Sport subclasses (e.g. PGAShowdown, PGAWeekend).",
    )
    parser.add_argument("-l", "--live", action="store_true", default="", help="Get live contests")
    parser.add_argument("-e", "--entry", type=int, default=25, help="Entry fee (25 for $25)")
    parser.add_argument(
        "--game-type-id",
        type=int,
        help="Optional DraftKings gameTypeId filter (e.g. 87 for standard Showdown).",
    )
    parser.add_argument("-q", "--query", help="Search contest name")
    parser.add_argument("-x", "--exclude", help="Exclude from search")
    parser.add_argument(
        "-d",
        "--date",
        help="The Start Date - format YYYY-MM-DD",
        default=datetime.datetime.today(),
        type=valid_date,
    )
    parser.add_argument(
        "--insert",
        action="store_true",
        help="After printing the matched contest, prompt to insert it into contests.db",
    )
    args = parser.parse_args()
    print(args)

    is_live = bool(args.live)

    if args.sport_class and args.live:
        parser.error("--live is only supported with --sport legacy mode.")

    if args.sport_class:
        selected_sport = args.sport_class
        sport_obj = sport_class_choices[args.sport_class]
        response = get_lobby_response(sport_obj.get_primary_sport(), live=False)
        if not isinstance(response, dict):
            raise SystemExit("Sport-class mode requires getcontests response with DraftGroups.")
        draft_groups = set(filter_draft_groups(response["DraftGroups"], sport_obj))
        response_contests = [
            contest for contest in get_contests_from_response(response) if contest.get("dg") in draft_groups
        ]
    else:
        selected_sport = args.sport
        response = get_lobby_response(args.sport, live=is_live)
        response_contests = get_contests_from_response(response)

    # create list of Contest objects
    contests = [Contest.from_lobby(c, selected_sport) for c in response_contests]

    # print stats for contests
    print_stats(contests)

    # parse contest and return single contest which matches argument criteria,
    # falling back to lower double-up fee tiers if args.entry has no match
    contest = get_largest_contest_with_fallback(
        contests,
        args.date,
        args.entry,
        args.query,
        args.exclude,
        game_type_id=args.game_type_id,
    )

    # check if contest is empty
    if not contest:
        exit("No contests found.")

    print_sql_insert(contest)
    maybe_insert_contest(contest, args.insert)


if __name__ == "__main__":
    main()
