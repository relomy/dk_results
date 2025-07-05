import argparse
import csv
from datetime import datetime

import requests

from classes.cookieservice import get_dk_cookies


def download_salary_csv(filename, csv_url):
    """Given a filename and CSV URL, request download of CSV file and save to filename."""
    # set cookies based on Chrome session
    _, cookies = get_dk_cookies()

    # send GET request
    r = requests.get(csv_url, cookies=cookies)

    # if not successful, raise an exception
    if r.status_code != 200:
        raise Exception("Requests status != 200. It is: {0}".format(r.status_code))

    # dump html to file to avoid multiple requests
    with open(filename, "w") as outfile:
        print("Writing r.text to {}".format(filename))
        print(r.text, file=outfile)


def pull_salary_csv(filename, csv_url):
    """Pull CSV for salary information."""
    with requests.Session() as s:
        download = s.get(csv_url)

        decoded_content = download.content.decode("utf-8")

        cr = csv.reader(decoded_content.splitlines(), delimiter=",")
        my_list = list(cr)

        return my_list


def get_csv_url(sport, contests):
    """Given a sport, return the salary export URL based on game_type/group_id."""
    for k, v in contests.items():
        if sport in v["name"]:
            game_type = v["game_type"]
            group_id = v["group_id"]
            csv_url = "https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={0}&draftGroupId={1}".format(
                game_type, group_id
            )
            return csv_url


def main():
    """Download salary file given a sport, draftgroup, and filename."""
    # dir = "/home/pi/Desktop/dk_salary_owner/"

    # parse arguments
    arg_parser = argparse.ArgumentParser()
    choices = ["NBA", "NFL", "CFB", "PGA", "NHL", "MLB", "TEN", "XFL"]
    arg_parser.add_argument(
        "-s",
        "--sport",
        choices=choices,
        required=True,
        help="Type of contest (NBA, NFL, PGA, CFB, NHL, TEN, or XFL)",
    )
    arg_parser.add_argument(
        "-dg", "--draft_group", type=int, required=True, help="Draft Group ID"
    )
    arg_parser.add_argument("-f", "--filename", help="Output filename")
    args = arg_parser.parse_args()

    contest_type_id = {
        "PGA": 9,
        "SOC": 10,
        "MLB": 12,
        "NFL": 21,
        "NBA": 70,
        "CFB": 94,
        "TEN": 106,
        "XFL": 134,
    }

    if args.sport:
        now = datetime.now()
        print("Current time: {}".format(now))
        # set the filename for the salary CSV
        if args.filename:
            fn = args.filename
        else:
            fn = "DKSalaries_{}_{}.csv".format(args.sport, now.strftime("%A"))

        if args.sport in contest_type_id:
            print(
                "contest_type_id [{}]: {}".format(
                    args.sport, contest_type_id[args.sport]
                )
            )
        else:
            raise Exception(
                "Sport {} not in contest_type_id dictionary".format(args.sport)
            )

        csv_url = "https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={0}&draftGroupId={1}".format(
            contest_type_id[args.sport], args.draft_group
        )
        print(csv_url)
        # download_salary_csv(dir + fn, csv_url)
        download_salary_csv(fn, csv_url)


if __name__ == "__main__":
    main()
