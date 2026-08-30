"""Default object-store adapter: boto3 against R2's S3-compatible endpoint.

Chosen over ``wrangler`` per ADR-0007 (Python-only footprint on the Pi).
Credentials and endpoint come from the environment; the bucket name comes from
configuration so renaming it in the dashboard needs no code change here.

The boto3 client is injectable so the key/content-type mapping is unit-tested in
isolation, and boto3 is imported lazily so tests never require it installed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from dk_results.feed.object_store import ObjectStoreError
from dk_results.services.json_stable import to_stable_json

logger = logging.getLogger(__name__)

_MISSING_KEY_CODES = {"NoSuchKey", "NotFound", "404"}


@dataclass(frozen=True)
class R2Config:
    """R2 connection settings: bucket from config, credentials from the env."""

    bucket: str
    account_id: str
    access_key_id: str
    secret_access_key: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "R2Config":
        source = os.environ if env is None else env
        missing = [
            name
            for name in ("R2_BUCKET", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
            if not str(source.get(name) or "").strip()
        ]
        if missing:
            raise ObjectStoreError(f"Missing R2 configuration: {', '.join(missing)}")
        return cls(
            bucket=str(source["R2_BUCKET"]).strip(),
            account_id=str(source["R2_ACCOUNT_ID"]).strip(),
            access_key_id=str(source["R2_ACCESS_KEY_ID"]).strip(),
            secret_access_key=str(source["R2_SECRET_ACCESS_KEY"]).strip(),
        )


def _is_missing_key(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code") or "")
    return code in _MISSING_KEY_CODES


class R2ObjectStore:
    """boto3-backed :class:`~dk_results.feed.object_store.ObjectStore` for R2."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "R2ObjectStore":
        config = R2Config.from_env(env)
        import boto3  # imported lazily so hermetic tests never require it

        client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
        )
        return cls(client, config.bucket)

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - narrowed below
            if _is_missing_key(exc):
                return None
            raise ObjectStoreError(f"Failed to read object {key}") from exc
        body = response["Body"].read()
        return dict(json.loads(body))

    def put_json(
        self,
        key: str,
        body: dict[str, Any],
        content_type: str = "application/json",
    ) -> None:
        payload = to_stable_json(body).encode("utf-8")
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as ObjectStoreError
            raise ObjectStoreError(f"Failed to write object {key}") from exc
