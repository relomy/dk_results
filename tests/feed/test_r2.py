import io

import pytest

from dk_results.feed.object_store import ObjectStoreError
from dk_results.feed.r2 import R2Config, R2ObjectStore
from dk_results.services.json_stable import to_stable_json


class _MissingKey(Exception):
    def __init__(self, code: str = "NoSuchKey") -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    def __init__(self) -> None:
        self.puts: list[dict] = []
        self.blobs: dict[str, bytes] = {}

    def put_object(self, **kwargs) -> dict:
        self.puts.append(kwargs)
        self.blobs[kwargs["Key"]] = kwargs["Body"]
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803 - boto3 kwargs
        if Key not in self.blobs:
            raise _MissingKey()
        return {"Body": io.BytesIO(self.blobs[Key])}


def test_put_json_maps_key_body_and_content_type():
    client = FakeS3Client()
    store = R2ObjectStore(client, bucket="dk-dashboard-data")

    body = {"b": 2, "a": 1}
    store.put_json("latest.json", body)

    assert len(client.puts) == 1
    call = client.puts[0]
    assert call["Bucket"] == "dk-dashboard-data"
    assert call["Key"] == "latest.json"
    assert call["ContentType"] == "application/json"
    # Stored bytes are the repo's stable JSON encoding.
    assert call["Body"] == to_stable_json(body).encode("utf-8")


def test_put_json_honors_explicit_content_type():
    client = FakeS3Client()
    store = R2ObjectStore(client, bucket="dk-dashboard-data")

    store.put_json("manifest/2026-02-15.json", {"x": 1}, content_type="application/json; charset=utf-8")

    assert client.puts[0]["ContentType"] == "application/json; charset=utf-8"


def test_get_json_round_trips_through_the_store():
    client = FakeS3Client()
    store = R2ObjectStore(client, bucket="dk-dashboard-data")

    store.put_json("manifest/2026-02-15.json", {"snapshots": [1, 2, 3]})
    assert store.get_json("manifest/2026-02-15.json") == {"snapshots": [1, 2, 3]}


def test_get_json_returns_none_for_missing_key():
    client = FakeS3Client()
    store = R2ObjectStore(client, bucket="dk-dashboard-data")

    assert store.get_json("manifest/does-not-exist.json") is None


def test_get_json_wraps_unexpected_errors():
    class BrokenClient:
        def get_object(self, **_kwargs):
            raise RuntimeError("network down")

    store = R2ObjectStore(BrokenClient(), bucket="dk-dashboard-data")
    with pytest.raises(ObjectStoreError):
        store.get_json("latest.json")


def test_put_json_wraps_unexpected_errors():
    class BrokenClient:
        def put_object(self, **_kwargs):
            raise RuntimeError("network down")

    store = R2ObjectStore(BrokenClient(), bucket="dk-dashboard-data")
    with pytest.raises(ObjectStoreError):
        store.put_json("latest.json", {"a": 1})


def test_config_from_env_reads_settings_and_builds_endpoint():
    env = {
        "R2_BUCKET": "dk-dashboard-data",
        "R2_ACCOUNT_ID": "acct123",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
    }
    config = R2Config.from_env(env)

    assert config.bucket == "dk-dashboard-data"
    assert config.endpoint_url == "https://acct123.r2.cloudflarestorage.com"


def test_config_from_env_reports_missing_settings():
    with pytest.raises(ObjectStoreError) as excinfo:
        R2Config.from_env({"R2_BUCKET": "dk-dashboard-data"})

    message = str(excinfo.value)
    assert "R2_ACCOUNT_ID" in message
    assert "R2_ACCESS_KEY_ID" in message
    assert "R2_SECRET_ACCESS_KEY" in message
