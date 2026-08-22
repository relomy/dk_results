from pathlib import Path

DOMAIN_MODULES = {
    "bonus_rules",
    "contest",
    "contest_standings",
    "dfs_sheet_domain",
    "lineup",
    "player",
    "sport",
    "user",
}
ANALYTICS_MODULES = {"optimizer", "trainfinder"}


def test_domain_and_analytics_modules_use_semantic_packages() -> None:
    source_root = Path(__file__).parents[1] / "src" / "dk_results"

    assert (source_root / "domain" / "__init__.py").is_file()
    assert (source_root / "analytics" / "__init__.py").is_file()

    for module in DOMAIN_MODULES:
        assert (source_root / "domain" / f"{module}.py").is_file()
        assert not (source_root / "classes" / f"{module}.py").exists()

    for module in ANALYTICS_MODULES:
        assert (source_root / "analytics" / f"{module}.py").is_file()
        assert not (source_root / "classes" / f"{module}.py").exists()
