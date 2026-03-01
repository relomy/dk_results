"""Shared VIP configuration helpers."""

from __future__ import annotations

import logging

import yaml

from dk_results.paths import repo_file

logger = logging.getLogger(__name__)


def load_vips() -> list[str]:
    vip_path = repo_file("vips.yaml")
    try:
        with open(vip_path, "r", encoding="utf-8") as handle:
            vips = yaml.safe_load(handle) or []
        if not isinstance(vips, list):
            return []
        return [str(value).strip() for value in vips if str(value).strip()]
    except Exception:
        logger.debug("Failed to load VIPs from %s", vip_path, exc_info=True)
        return []
