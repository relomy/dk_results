from importlib.util import find_spec
from pathlib import Path


def test_schema_three_has_one_snapshot_generation_surface() -> None:
    services_dir = Path(__file__).parents[2] / "src" / "dk_results" / "services"

    assert not (services_dir / "snapshot_v3.py").exists()
    assert find_spec("dk_results.services.snapshot_v3.pipeline") is not None
    assert find_spec("dk_results.services.snapshot_v3.serialize") is not None
