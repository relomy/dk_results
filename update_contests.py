import logging
import coloredlogs
import logging.config
import sqlite3
from os import getenv
from time import sleep

import selenium.webdriver.chrome.service as chrome_service
from bs4 import BeautifulSoup
from selenium import webdriver


# load the logging configuration
# logging.config.fileConfig("logging.ini")

logger = logging.getLogger(__name__)

coloredlogs.install(level="DEBUG", logger=logger)


def check_contests_for_completion(conn):
    """Check each contest for completion/positions_paid data."""
    # get incopmlete contests from the database
    incomplete_contests = db_get_incomplete_contests(conn)

    # if there are no incomplete contests, return
    if not incomplete_contests:
        return

    logger.debug("found %i incomplete contests", len(incomplete_contests))

    # start chromium driver
    logger.debug("starting driver")
    bin_chromedriver = getenv("CHROMEDRIVER")
    if not getenv("CHROMEDRIVER"):
        raise "Could not find CHROMEDRIVER in environment"

    # start webdriver
    logger.debug("starting chromedriver..")
    service = chrome_service.Service(bin_chromedriver)
    service.start()
    options = webdriver.ChromeOptions()
    # TODO try headless? probably won't work due to the geolocation stuff
    # options.headless = True
    options.add_argument("--no-sandbox")
    #options.add_argument("--user-data-dir='~/Library/Application Support/Google/Chrome/Default'")
    options.add_argument("--user-data-dir=/home/pi/.config/chromium")
    options.add_argument(r"--profile-directory=Profile 1")
    driver = webdriver.Remote(service.service_url, options=options  )

    skip_draft_groups = []

    for (
        dk_id,
        draft_group,
        positions_paid,
        status,
        completed,
        name,
        start_date,
    ) in incomplete_contests:
        if positions_paid is not None and draft_group in skip_draft_groups:
            logger.debug("dk_id: {} positions_paid: {}".format(dk_id, positions_paid))
            logger.debug(
                "skipping %s because we've already updated %d [skipped draft groups %s]",
                name,
                draft_group,
                " ".join(str(dg) for dg in skip_draft_groups),
            )
            continue

        # navigate to the gamecenter URL
        url = f"https://www.draftkings.com/contest/gamecenter/{dk_id}"
        logger.debug("driver.get url %s", url)
        driver.get(url)

        logger.debug(
            "getting contest data for %s [id: %i start: %s dg: %d]",
            name,
            dk_id,
            start_date,
            draft_group,
        )

        contest_data = get_contest_data(driver.page_source, dk_id)

        # try again in case geo-check
        if contest_data is None:
            contest_data = get_contest_data(driver.page_source, dk_id)

        if not contest_data:
            continue

        # if contest data is different, update it
        if (
            positions_paid != contest_data["positions_paid"]
            or status != contest_data["status"]
            or completed != contest_data["completed"]
        ):
            #            logger.debug("trying to update contest %i", dk_id)
            db_update_contest(
                conn,
                [
                    contest_data["positions_paid"],
                    contest_data["status"],
                    contest_data["completed"],
                    dk_id,
                ],
            )
        else:
            # if contest data is the same, don't update other contests in the same draft group
            skip_draft_groups.append(draft_group)
            logger.debug("contest data is the same, not updating")

    logger.debug("quitting driver")
    driver.quit()


def db_update_contest(conn, contest_to_update):
    """Update contest fields based on get_contest_data()."""
    logger.debug("trying to update contest %i", contest_to_update[3])
    cur = conn.cursor()

    sql = (
        "UPDATE contests "
        "SET positions_paid=?, status=?, completed=? "
        "WHERE dk_id=?"
    )

    try:
        cur.execute(sql, contest_to_update)
        conn.commit()
        logger.info("Total %d records updated successfully!", cur.rowcount)
    except sqlite3.Error as err:
        logger.error("sqlite error: %s", err.args[0])


def db_get_incomplete_contests(conn):
    """Get the incomplete contests from the database."""
    # get cursor
    cur = conn.cursor()

    try:
        # execute SQL command
        sql = (
            "SELECT dk_id, draft_group, positions_paid, status, completed, name, start_date "
            "FROM contests "
            "WHERE start_date <= datetime('now', 'localtime') "
            "  AND (positions_paid IS NULL OR completed = 0)"
        )
        cur.execute(sql)

        # return all rows
        return cur.fetchall()
    except sqlite3.Error as err:
        print("sqlite error [check_db_contests_for_completion()]: ", err.args[0])

    return None


def get_contest_data(html, contest_id):
    """Pull contest data (positions paid, status, etc.) with BeautifulSoup."""

    # get the HTML using selenium, since there is html loaded with javascript
    if not html:
        logger.warning("couldn't get HTML for contest_id %d", contest_id)
        return None

    logger.debug("parsing html for contest %i", contest_id)
    soup = BeautifulSoup(html, "html.parser")

    try:
        # found_user = False
        # scripts = soup.findAll('script')
        # print(scripts, file=open("user_check.html", "w"))
        # count = 1
        # for script in scripts:            
        #     if count == 2:
        #         break
        #     logger.debug(type(script))
        #     logger.debug(vars(script))
        #Hereug(f"found relomy in script tag #{count}")
        #         found_user = True
        #         break
        #     else:
        #         logger.debug(f"could not find relomy in script tag #{count}")
            
        #     count += 1
        
        geo_check = soup.find("div", {"class": "searching-geolocation-overlay"})
        if geo_check:
            logger.debug("found geo_check - waiting 5 seconds")
            # logger.debug("geo_check: {}".format(geo_check))
            sleep(5)
        # searching-geolocation-overlay

        logger.debug("re-parsing html for contest %i after geo_check", contest_id)
        soup = BeautifulSoup(html, "html.parser")
        print(html, file=open("output.html", "w"))

        logger.debug("looking for entries...")
        entries = soup.find("label", string="Entries").find_next("span").text
        logger.debug("entries: %s", entries)

        status = soup.find("label", string="Status").find_next("span").text.upper()
        logger.debug("status: %s", status)

        positions_paid = (
            soup.find("label", string="Positions Paid").find_next("span").text
        )
        logger.debug("positions_paid: %s", positions_paid)

        if status in ["COMPLETED", "LIVE", "CANCELLED"]:
            # set completed status
            completed = 1 if status in ["COMPLETED", "CANCELLED"] else 0
            return {
                "completed": completed,
                "status": status,
                "entries": int(entries.replace(",", "")),
                "positions_paid": int(positions_paid.replace(",", "")),
                # "name": header[0].string,
                # "total_prizes": header[1].string,
                # "date": info_header[0].string,
            }

        return None
    except (IndexError, AttributeError) as ex:
        # This error occurs for old contests whose pages no longer are being served.
        # IndexError: list index out of range
        # logger.debug("driver.get url %s", driver.current_url)
        logger.error("Couldn't find DK contest with id %d error: %s", contest_id, ex)
        print(html, file=open("debug.html", "w"))
        return None


def main():
    conn = sqlite3.connect("contests.db")
    # update old contests
    check_contests_for_completion(conn)


if __name__ == "__main__":
    main()
