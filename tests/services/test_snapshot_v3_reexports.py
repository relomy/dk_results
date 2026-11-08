"""The snapshot_v3 modules keep re-exporting the names that moved to presence_rules and source_bundle."""

from dk_results.services.snapshot_v3 import collector, presence_rules, source_bundle, validate


def test_validate_re_exports_the_presence_rule_names() -> None:
    assert validate.PresenceRule is presence_rules.PresenceRule
    assert validate.PresenceWarningRow is presence_rules.PresenceWarningRow
    assert validate.collect_presence_warnings is presence_rules.collect_presence_warnings


def test_validate_declares_its_public_names() -> None:
    assert sorted(validate.__all__) == [
        "PresenceRule",
        "PresenceWarningRow",
        "collect_presence_warnings",
        "validate_v3_envelope",
    ]


def test_collector_re_exports_field_remaining() -> None:
    assert collector.FieldRemaining is source_bundle.FieldRemaining


def test_collector_declares_its_public_names() -> None:
    assert sorted(collector.__all__) == [
        "CollectedSnapshot",
        "FieldRemaining",
        "collect_raw_bundle",
        "collect_snapshot",
    ]
