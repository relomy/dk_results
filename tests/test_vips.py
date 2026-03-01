from pathlib import Path

from dk_results.services import vips


def test_load_vips_returns_sanitized_values(monkeypatch, tmp_path: Path) -> None:
    vip_file = tmp_path / "vips.yaml"
    vip_file.write_text("- vip_one\n- ' vip_two '\n- ''\n", encoding="utf-8")
    monkeypatch.setattr(vips, "repo_file", lambda *parts: vip_file)

    assert vips.load_vips() == ["vip_one", "vip_two"]


def test_load_vips_returns_empty_list_for_invalid_yaml(monkeypatch, tmp_path: Path) -> None:
    vip_file = tmp_path / "vips.yaml"
    vip_file.write_text("key: value\n", encoding="utf-8")
    monkeypatch.setattr(vips, "repo_file", lambda *parts: vip_file)

    assert vips.load_vips() == []


def test_load_vips_returns_empty_list_for_missing_file(monkeypatch, tmp_path: Path) -> None:
    missing_file = tmp_path / "missing-vips.yaml"
    monkeypatch.setattr(vips, "repo_file", lambda *parts: missing_file)

    assert vips.load_vips() == []
