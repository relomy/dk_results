import ast
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
PACKAGE_MODULES = {
    "sheets": {"dfs_sheet_repository", "dfs_sheet_service", "sheets_service"},
    "draftkings": {"cookies", "session", "client"},
    "persistence": {"contestdatabase", "notification_store"},
    "notifications": {"bonus_announcements", "vip_presence"},
}


def test_domain_and_analytics_modules_use_semantic_packages() -> None:
    source_root = Path(__file__).parents[1] / "src" / "dk_results"

    assert (source_root / "domain" / "__init__.py").is_file()
    assert (source_root / "analytics" / "__init__.py").is_file()

    for module in DOMAIN_MODULES:
        assert (source_root / "domain" / f"{module}.py").is_file()

    for module in ANALYTICS_MODULES:
        assert (source_root / "analytics" / f"{module}.py").is_file()

    for package, modules in PACKAGE_MODULES.items():
        assert (source_root / package / "__init__.py").is_file()
        for module in modules:
            assert (source_root / package / f"{module}.py").is_file()

    assert not any(path.name == "classes" for path in source_root.iterdir())


def test_semantic_packages_do_not_reexport_modules() -> None:
    source_root = Path(__file__).parents[1] / "src" / "dk_results"

    for package in PACKAGE_MODULES.keys() - {"draftkings"}:
        tree = ast.parse((source_root / package / "__init__.py").read_text())
        assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)


def test_draftkings_exports_its_concrete_adapter() -> None:
    from dk_results.draftkings import DraftKings

    assert DraftKings.__name__ == "DraftKings"
