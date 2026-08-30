"""Snapshot feed: build → publish → load a snapshot into the object store.

The feed is the committed, scheduled replacement for the hand-run
``export_fixture … && export_fixture publish && wrangler r2 object put …``
recipe. It reuses the existing build and publish steps and owns only the
load step (uploading ``snapshots/*``, ``manifest/*``, and ``latest.json`` into
the object store) and the end-to-end orchestration.
"""

from dk_results.feed.object_store import ObjectStore, ObjectStoreError
from dk_results.feed.pipeline import FeedResult, run_feed

__all__ = ["ObjectStore", "ObjectStoreError", "FeedResult", "run_feed"]
