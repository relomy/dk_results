"""CompletionProcessor logs a failed contest and moves on, instead of raising."""

import logging


def test_undecodable_contest_detail_is_logged_and_skipped(
    conn, sender, insert_contest, make_results, make_processor, caplog
):
    insert_contest()
    processor = make_processor(results=make_results(detail_error=ValueError("bad json")), sender=sender)
    with caplog.at_level(logging.ERROR):
        processor.run(conn)
    assert "JSON decoding error: bad json" in caplog.messages
    assert sender.messages == []


def test_contest_detail_missing_fields_is_logged_and_skipped(
    conn, sender, insert_contest, make_results, make_processor, caplog
):
    insert_contest()
    processor = make_processor(results=make_results(detail={"contestDetail": {}}), sender=sender)
    with caplog.at_level(logging.ERROR):
        processor.run(conn)
    assert "Key error: 'payoutSummary'" in caplog.messages
    assert sender.messages == []


def test_contest_detail_request_failure_is_logged_with_traceback(
    conn, insert_contest, make_results, make_processor, caplog
):
    insert_contest()
    results = make_results(detail_error=RuntimeError("connection reset"))
    processor = make_processor(results=results, sender=None)

    with caplog.at_level(logging.ERROR):
        processor.run(conn)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage() == "Request error"
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is RuntimeError


def test_failing_contest_sync_is_logged_with_traceback_and_contest_id(
    conn, failing_sender, insert_contest, detail, make_results, make_processor, caplog
):
    insert_contest()
    results = make_results(detail=detail(status="LIVE"))
    processor = make_processor(results=results, sender=failing_sender)

    with caplog.at_level(logging.ERROR):
        processor.run(conn)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage() == "Failed to sync contest dk_id=1"
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is RuntimeError


def test_a_failing_contest_does_not_stop_the_next_contest_from_syncing(
    conn, failing_sender, insert_contest, contest_row, detail, make_results, make_processor
):
    insert_contest(dk_id=1, draft_group=1)
    insert_contest(dk_id=2, draft_group=2)
    processor = make_processor(results=make_results(detail=detail(status="LIVE")), sender=failing_sender)

    processor.run(conn)

    assert (contest_row(1), contest_row(2)) == ((10, "LIVE", 0), (10, "LIVE", 0))
