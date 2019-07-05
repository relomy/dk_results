import argparse
import datetime

from classes.results import Results

# if __name__ == "__main__":
"""Use contest ID to update Google Sheet with DFS results.

Example export CSV/ZIP link
https://www.draftkings.com/contest/exportfullstandingscsv/62753724

Example salary CSV link
https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=70&draftGroupId=22401
12 = MLB 21 = NFL 9 = PGA 24 = NASCAR 10 = Soccer 13 = MMA
"""

# parse arguments
parser = argparse.ArgumentParser()
choices = ['NBA', 'NFL', 'CFB', 'PGAMain',
           'PGAWeekend', 'PGAShowdown', 'NHL', 'MLB', 'TEN']
parser.add_argument('-i', '--id', type=int, required=True,
                    help='Contest ID from DraftKings',)
parser.add_argument('-c', '--csv', help='Slate CSV from DraftKings',)
parser.add_argument('-s', '--sport', choices=choices,
                    required=True, help='Type of contest (NBA, NFL, PGA, CFB, NHL, or MLB)')
parser.add_argument('-v', '--verbose', help='Increase verbosity')
args = parser.parse_args()

now = datetime.datetime.now()

Results(args.sport, args.id, args.csv)
