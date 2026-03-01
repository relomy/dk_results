from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope


def test_build_snapshot_v3_envelope_normalizes_generated_at_and_orders_sports(monkeypatch) -> None:
    build_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.collect_raw_bundle",
        lambda *, sport, contest_id, standings_limit: {
            "sport": sport,
            "contest": {"contest_id": str(contest_id or sport)},
        },
    )

    def _fake_build_sport_payload(raw_bundle, *, derived, generated_at):
        build_calls.append((str(raw_bundle["sport"]), generated_at))
        return {
            "status": "ok",
            "updated_at": generated_at,
            "players": [],
            "primary_contest": {
                "contest_id": str(raw_bundle["contest"]["contest_id"]),
                "contest_key": f"{str(raw_bundle['sport']).lower()}:{raw_bundle['contest']['contest_id']}",
                "selection_reason": {"mode": "explicit_id"},
                "selected_at": generated_at,
            },
            "contests": [
                {
                    "contest_id": str(raw_bundle["contest"]["contest_id"]),
                    "contest_key": f"{str(raw_bundle['sport']).lower()}:{raw_bundle['contest']['contest_id']}",
                    "name": f"{raw_bundle['sport']} Contest",
                    "sport": str(raw_bundle["sport"]).lower(),
                    "contest_type": "classic",
                    "start_time": generated_at,
                    "state": "live",
                    "entry_fee_cents": 1000,
                    "prize_pool_cents": 100000,
                    "currency": "USD",
                    "max_entries": 100,
                }
            ],
        }

    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.build_sport_payload", _fake_build_sport_payload)
    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.validate_v3_envelope", lambda payload: [])

    envelope = build_snapshot_v3_envelope(
        {"NBA": 188080404, "GOLF": 187937165},
        standings_limit=42,
        generated_at="2026-03-01T12:34:56.999+00:00",
    )

    assert envelope["schema_version"] == 3
    assert envelope["snapshot_at"] == "2026-03-01T12:34:56Z"
    assert envelope["generated_at"] == "2026-03-01T12:34:56Z"
    assert list(envelope["sports"].keys()) == ["golf", "nba"]
    assert build_calls == [
        ("GOLF", "2026-03-01T12:34:56Z"),
        ("NBA", "2026-03-01T12:34:56Z"),
    ]


def test_build_snapshot_v3_envelope_raises_on_validation_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.collect_raw_bundle",
        lambda *, sport, contest_id, standings_limit: {
            "sport": sport,
            "contest": {"contest_id": str(contest_id or "1")},
        },
    )
    monkeypatch.setattr(
        "dk_results.services.snapshot_v3.pipeline.build_sport_payload",
        lambda raw_bundle, *, derived, generated_at: {
            "status": "ok",
            "updated_at": generated_at,
            "players": [],
            "primary_contest": {
                "contest_id": "1",
                "contest_key": "nba:1",
                "selection_reason": {"mode": "explicit_id"},
                "selected_at": generated_at,
            },
            "contests": [],
        },
    )
    monkeypatch.setattr("dk_results.services.snapshot_v3.pipeline.validate_v3_envelope", lambda payload: ["bad"])

    try:
        build_snapshot_v3_envelope({"NBA": 1})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Snapshot v3 validation failed: bad" in str(exc)
