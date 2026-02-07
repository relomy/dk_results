"""Factory for building SheetClient instances for dk_results."""

import logging
import os
from typing import Any

from dfs_common.sheets import SheetClient, get_sheet_gids, service_account_provider


def _resolve_spreadsheet_id(spreadsheet_id: str | None) -> str | None:
    if spreadsheet_id is not None:
        return spreadsheet_id
    return os.getenv("SPREADSHEET_ID")


def make_sheet_client(
    spreadsheet_id: str | None = None,
    *,
    service: Any | None = None,
    credentials_provider: Any | None = None,
    logger: logging.Logger | None = None,
) -> SheetClient:
    resolved_spreadsheet_id = _resolve_spreadsheet_id(spreadsheet_id)
    if credentials_provider is None and service is None:
        credentials_provider = service_account_provider("client_secret.json")
    return SheetClient(
        spreadsheet_id=resolved_spreadsheet_id,
        service=service,
        credentials_provider=credentials_provider,
        logger=logger,
    )


def fetch_sheet_gids(spreadsheet_id: str | None = None) -> dict[str, int]:
    client = make_sheet_client(spreadsheet_id=spreadsheet_id)
    if client.spreadsheet_id is None:
        raise RuntimeError("SPREADSHEET_ID is not set.")
    return get_sheet_gids(client.service, client.spreadsheet_id)
