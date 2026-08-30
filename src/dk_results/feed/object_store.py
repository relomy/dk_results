"""Object-store port for the snapshot feed.

The feed's load step talks to the dashboard's object store (Cloudflare R2)
through this narrow interface, injected into the pipeline. Tests substitute a
fake in-memory store at this seam so CI never touches real credentials or the
network.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ObjectStoreError(RuntimeError):
    """Raised when an object-store operation fails."""


@runtime_checkable
class ObjectStore(Protocol):
    """The keyed JSON store the feed reads the day manifest from and loads into.

    Keys are object-store paths the dashboard already reads
    (``snapshots/<name>.json``, ``manifest/<date>.json``, ``latest.json``).
    Implementations must raise :class:`ObjectStoreError` on a failed write so a
    partial run never advances the latest pointer.
    """

    def get_json(self, key: str) -> dict[str, Any] | None:
        """Return the JSON object stored at ``key``, or ``None`` if absent."""
        ...

    def put_json(
        self,
        key: str,
        body: dict[str, Any],
        content_type: str = "application/json",
    ) -> None:
        """Store ``body`` as JSON at ``key`` with the given ``content_type``."""
        ...
