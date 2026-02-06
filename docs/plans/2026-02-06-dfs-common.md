# dfs_common Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deduplicate shared Google Sheets + Discord primitives into a new sibling repo `dfs_common` and migrate each app repo via wrappers and contract tests.

**Architecture:** Create `dfs_common` as a small, dependency-light package with `sheets` and `discord` modules. Each app repo keeps its existing public helpers but delegates to `dfs_common` internally, preserving behavior and tests.

**Tech Stack:** Python, uv, pytest, ruff, requests, google-api-python-client

---

### Task 1: Initialize `dfs_common` Repo Skeleton

**Files:**
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/pyproject.toml`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/README.md`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/.gitignore`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/__init__.py`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/sheets.py`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/discord.py`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/tests/test_sheets.py`
- Create: `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/tests/test_discord.py`

**Step 1: Create repo directory**

Run:
```bash
mkdir -p /Users/alewando/Documents/Repo/dfs-workspace/dfs_common
```
Expected: directory exists

**Step 2: Initialize git**

Run:
```bash
cd /Users/alewando/Documents/Repo/dfs-workspace/dfs_common
git init
```
Expected: empty git repo initialized

**Step 3: Add `pyproject.toml`**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/pyproject.toml`:
```toml
[project]
name = "dfs-common"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
  "requests",
  "google-api-python-client",
  "google-auth",
]

[dependency-groups]
dev = ["pytest", "ruff"]

[tool.uv]
package = true
```

**Step 4: Add `.gitignore`**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/.gitignore`:
```gitignore
.venv/
__pycache__/
*.py[cod]
.DS_Store
```

**Step 5: Add minimal package init**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/__init__.py`:
```python
__all__ = ["sheets", "discord"]
```

**Step 6: Add failing tests for Sheets and Discord**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/tests/test_sheets.py`:
```python
from dfs_common import sheets


def test_find_sheet_id_uses_service() -> None:
    class _Sheets:
        def get(self, spreadsheetId):
            return self
        def execute(self):
            return {"sheets": [{"properties": {"title": "NBA", "sheetId": 99}}]}
    class _Service:
        def spreadsheets(self):
            return _Sheets()

    client = sheets.SheetClient(spreadsheet_id="abc", service=_Service())
    assert client.find_sheet_id("NBA") == 99


def test_write_values_uses_user_entered() -> None:
    calls = {}
    class _Values:
        def update(self, **kwargs):
            calls.update(kwargs)
            return self
        def execute(self):
            return {"updatedCells": 3, "updatedRange": "Sheet1!A1"}
    class _Sheets:
        def values(self):
            return _Values()
    class _Service:
        def spreadsheets(self):
            return _Sheets()

    client = sheets.SheetClient(spreadsheet_id="abc", service=_Service())
    client.write_values([["a"]], "Sheet1!A1")
    assert calls["valueInputOption"] == "USER_ENTERED"
```

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/tests/test_discord.py`:
```python
from dfs_common import discord


def test_webhook_sender_posts(monkeypatch):
    sent = {}
    def fake_post(url, json=None, timeout=None, headers=None):
        sent["url"] = url
        sent["json"] = json
        return type("Resp", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(discord.requests, "post", fake_post)
    sender = discord.WebhookSender("http://example")
    sender.send_message("hello")
    assert sent["json"]["content"] == "hello"
```

**Step 7: Run tests to verify they fail**

Run:
```bash
cd /Users/alewando/Documents/Repo/dfs-workspace/dfs_common
uv sync
uv run pytest -q
```
Expected: FAIL with missing implementations

**Step 8: Implement minimal `sheets` module**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/sheets.py`:
```python
import logging
from typing import Any, Callable, Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import build

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CredentialsProvider = Callable[[], Any]


def service_account_provider(
    secret_file: str = "client_secret.json",
    scopes: Iterable[str] = DEFAULT_SCOPES,
) -> CredentialsProvider:
    def _provider() -> Any:
        credentials = service_account.Credentials.from_service_account_file(
            secret_file, scopes=list(scopes)
        )
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _provider


class SheetClient:
    def __init__(
        self,
        spreadsheet_id: str,
        *,
        service: Any | None = None,
        credentials_provider: CredentialsProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.logger = logger or logging.getLogger(__name__)
        self._service = service
        self._credentials_provider = credentials_provider

    @property
    def service(self) -> Any:
        if self._service is None:
            if self._credentials_provider is None:
                raise RuntimeError("No Sheets service or credentials provider configured")
            self._service = self._credentials_provider()
        return self._service

    def find_sheet_id(self, title: str) -> int | None:
        sheet_metadata = (
            self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        for sheet in sheet_metadata.get("sheets", []):
            if title in sheet["properties"]["title"]:
                return sheet["properties"]["sheetId"]
        return None

    def write_values(
        self, values: list[list[Any]], cell_range: str, value_input_option: str = "USER_ENTERED"
    ) -> None:
        body = {"values": values}
        result = (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=cell_range,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute()
        )
        self.logger.debug("%s cells updated for %s", cell_range, result.get("updatedCells"))

    def clear_range(self, cell_range: str) -> None:
        result = (
            self.service.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self.spreadsheet_id,
                range=cell_range,
                body={},
            )
            .execute()
        )
        self.logger.debug("Range %s cleared", result.get("clearedRange"))

    def get_values(self, cell_range: str) -> list[list[Any]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=cell_range)
            .execute()
        )
        return result.get("values", [])
```

**Step 9: Implement minimal `discord` module**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dfs_common/src/dfs_common/discord.py`:
```python
import logging
import time
from typing import Iterable

import requests
from requests.exceptions import RequestException


class WebhookSender:
    def __init__(
        self,
        webhook: str,
        *,
        chunk_messages: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.webhook = webhook
        self.chunk_messages = chunk_messages
        self.logger = logger or logging.getLogger(__name__)

    def _chunk_message(self, text: str, limit: int = 1900) -> Iterable[str]:
        if not text:
            yield ""
            return
        parts = text.split("\n\n")
        buf = ""
        for p in parts:
            candidate = p if not buf else (buf + "\n\n" + p)
            if len(candidate) <= limit:
                buf = candidate
            else:
                if buf:
                    yield buf
                    buf = ""
                if len(p) <= limit:
                    yield p
                else:
                    lines = p.splitlines()
                    cur = ""
                    for line in lines:
                        cand = line if not cur else (cur + "\n" + line)
                        if len(cand) <= limit:
                            cur = cand
                        else:
                            if cur:
                                yield cur
                            remaining = line
                            while len(remaining) > limit:
                                yield remaining[:limit]
                                remaining = remaining[limit:]
                            cur = remaining
                    if cur:
                        yield cur
        if buf:
            yield buf

    def send_message(self, message: str) -> None:
        logger = self.logger
        chunks = [c for c in self._chunk_message(str(message) or "") if c.strip()]
        if not self.chunk_messages:
            chunks = chunks[:1]

        if not chunks:
            logger.warning("Discord: attempted to send an empty message; skipping.")
            return

        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            content = chunk if total == 1 else f"(part {idx}/{total})\n{chunk}"
            payload = {"content": content}
            try:
                resp = requests.post(self.webhook, json=payload, timeout=15)
            except RequestException as ex:
                logger.error("Discord webhook network error: %s", ex)
                continue
            if resp.status_code == 429:
                retry_after = 0.5
                try:
                    ra = resp.headers.get("Retry-After") or resp.json().get("retry_after")
                    if ra is not None:
                        retry_after = float(ra)
                except Exception:
                    pass
                logger.warning("Discord rate limited; sleeping for %.2fs", retry_after)
                time.sleep(retry_after)
                try:
                    resp = requests.post(self.webhook, json=payload, timeout=15)
                except RequestException as ex:
                    logger.error("Discord webhook retry failed: %s", ex)
                    continue
            if not (200 <= resp.status_code < 300):
                logger.error(
                    "Discord webhook post failed (status=%s): %s",
                    resp.status_code,
                    getattr(resp, "text", "<no body>")[:500],
                )
            elif total > 1:
                time.sleep(0.35)
```

**Step 10: Run tests to verify they pass**

Run:
```bash
cd /Users/alewando/Documents/Repo/dfs-workspace/dfs_common
uv run pytest -q
```
Expected: PASS

**Step 11: Commit**

Run:
```bash
git add pyproject.toml README.md .gitignore src/dfs_common tests
git commit -m "feat: scaffold dfs_common sheets and discord"
```

---

### Task 2: Add `dfs_common` dependency to each repo (path-based)

**Files:**
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/pyproject.toml`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/pyproject.toml`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/read_datagolf/pyproject.toml`

**Step 1: Add dependency in `dk_results`**

Update `dependencies` to include:
```toml
"dfs-common @ ../../dfs_common",
```

**Step 2: Add dependency in `nba_sheet`**

Update `dependencies` to include:
```toml
"dfs-common @ ../../dfs_common",
```

**Step 3: Add dependency in `read_datagolf`**

Update `dependencies` to include:
```toml
"dfs-common @ ../../dfs_common",
```

**Step 4: Run `uv sync` in each repo**

Run:
```bash
uv sync
```
Expected: installs local path dependency

**Step 5: Commit per repo**

Run in each repo:
```bash
git add pyproject.toml
git commit -m "chore: add dfs-common path dependency"
```

---

### Task 3: Migrate `read_datagolf` Sheets helpers via wrappers

**Files:**
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/read_datagolf/dfssheet.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/read_datagolf/tests/test_dfssheet.py` (create if missing)

**Step 1: Add a contract test for basic Sheets operations**

Create `/Users/alewando/Documents/Repo/dfs-workspace/read_datagolf/tests/test_dfssheet.py`:
```python
from dfssheet import Sheet


def test_sheet_write_values_delegates(monkeypatch):
    calls = {}
    class _Values:
        def update(self, **kwargs):
            calls.update(kwargs)
            return self
        def execute(self):
            return {"updatedCells": 1}
    class _Sheets:
        def values(self):
            return _Values()
        def get(self, spreadsheetId):
            return self
        def execute(self):
            return {"sheets": []}
    class _Service:
        def spreadsheets(self):
            return _Sheets()

    sheet = Sheet()
    sheet._client._service = _Service()
    sheet.write_values_to_sheet_range([["a"]], "A1")
    assert calls["range"] == "A1"
```

**Step 2: Run test to see failure**

Run:
```bash
cd /Users/alewando/Documents/Repo/dfs-workspace/read_datagolf
uv sync --extra dev
uv run pytest tests/test_dfssheet.py -q
```
Expected: FAIL (missing `_client`)

**Step 3: Update `dfssheet.py` to delegate to `dfs_common.sheets`**

Modify `/Users/alewando/Documents/Repo/dfs-workspace/read_datagolf/dfssheet.py`:
```python
from dfs_common.sheets import SheetClient, service_account_provider

class Sheet:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.spreadsheet_id = "1Jv5nT-yUoEarkzY5wa7RW0_y0Dqoj8_zDrjeDs-pHL4"
        self._client = SheetClient(
            spreadsheet_id=self.spreadsheet_id,
            credentials_provider=service_account_provider("client_secret.json"),
            logger=self.logger,
        )

    @property
    def service(self) -> Any:
        return self._client.service

    def find_sheet_id(self, title: str) -> Optional[int]:
        return self._client.find_sheet_id(title)

    def write_values_to_sheet_range(self, values, cell_range: str) -> None:
        self._client.write_values(list(list(v) for v in values), cell_range)

    def clear_sheet_range(self, cell_range: str) -> None:
        self._client.clear_range(cell_range)

    def get_values_from_range(self, cell_range: str):
        return self._client.get_values(cell_range)
```

**Step 4: Run tests**

Run:
```bash
uv run pytest tests/test_dfssheet.py -q
```
Expected: PASS

**Step 5: Commit**

Run:
```bash
git add dfssheet.py tests/test_dfssheet.py
git commit -m "refactor: delegate read_datagolf sheets to dfs-common"
```

---

### Task 4: Migrate `dk_results` Sheets + webhook sender via wrappers

**Files:**
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/classes/dfssheet.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/bot/discord.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/bot/webhook.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/tests/classes/test_dfssheet.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/tests/test_webhook.py` (create)

**Step 1: Add contract test for webhook sender**

Create `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/tests/test_webhook.py`:
```python
from bot.discord import Discord


def test_discord_webhook_posts(monkeypatch):
    sent = {}
    def fake_post(url, json=None, timeout=None, headers=None):
        sent["url"] = url
        sent["json"] = json
        return type("Resp", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr("bot.discord.requests.post", fake_post)
    bot = Discord("http://example")
    bot.send_message("hi")
    assert sent["json"]["content"] == "hi"
```

**Step 2: Update `classes/dfssheet.py` to use `SheetClient`**

Modify `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/classes/dfssheet.py`:
```python
from dfs_common.sheets import SheetClient, service_account_provider

class Sheet:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self._client = SheetClient(
            spreadsheet_id=self.spreadsheet_id,
            credentials_provider=service_account_provider("client_secret.json"),
            logger=self.logger,
        )

    def setup_service(self) -> Any:
        return self._client.service

    def _ensure_service(self) -> None:
        self._client.service

    def find_sheet_id(self, title: str) -> int | None:
        return self._client.find_sheet_id(title)

    def write_values_to_sheet_range(self, values: list[list[Any]], cell_range: str) -> None:
        self._client.write_values(values, cell_range)

    def clear_sheet_range(self, cell_range: str) -> None:
        self._client.clear_range(cell_range)

    def get_values_from_range(self, cell_range: str) -> list[list[Any]]:
        return self._client.get_values(cell_range)
```

**Step 3: Update webhook senders to wrap `dfs_common.discord.WebhookSender`**

Modify `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/bot/discord.py`:
```python
from dfs_common.discord import WebhookSender

class Discord(BotInterface):
    def __init__(self, webhook: str) -> None:
        self._sender = WebhookSender(webhook)

    def send_message(self, message: str) -> None:
        self._sender.send_message(message)
```

Modify `/Users/alewando/Documents/Repo/dfs-workspace/dk_results/bot/webhook.py` similarly:
```python
from dfs_common.discord import WebhookSender

class DiscordWebhook(BotInterface):
    def __init__(self, webhook: str) -> None:
        self._sender = WebhookSender(webhook)

    def send_message(self, message: str) -> None:
        self._sender.send_message(message)
```

**Step 4: Run tests**

Run:
```bash
uv sync
uv run pytest -q
```
Expected: PASS

**Step 5: Commit**

Run:
```bash
git add classes/dfssheet.py bot/discord.py bot/webhook.py tests/test_webhook.py
git commit -m "refactor: delegate dk_results sheets and discord to dfs-common"
```

---

### Task 5: Migrate `nba_sheet` Sheets + webhook sender via wrappers

**Files:**
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/services/google_sheets_service.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/bot/discord.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/tests/test_discord.py`
- Modify: `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/tests/test_google_sheets_service.py`

**Step 1: Update Google Sheets service to delegate to `SheetClient`**

Modify `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/services/google_sheets_service.py`:
```python
from dfs_common.sheets import SheetClient, service_account_provider

class Sheet:
    def __init__(self, spreadsheet_id: str, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.spreadsheet_id = spreadsheet_id
        self._client = SheetClient(
            spreadsheet_id=spreadsheet_id,
            credentials_provider=service_account_provider("client_secret.json"),
            logger=self.logger,
        )
        self.default_sheet_name = self.get_first_sheet_name()

    def get_first_sheet_name(self) -> str:
        sheet_metadata = (
            self._client.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        )
        return sheet_metadata.get("sheets", [])[0]["properties"]["title"]

    def write_values_to_sheet_range(self, values, cell_range: str, sheet_name: str | None = None) -> None:
        full_range = f"{sheet_name or self.default_sheet_name}!{cell_range}"
        self._client.write_values(values, full_range)

    def clear_sheet_range(self, cell_range: str, sheet_name: str | None = None) -> None:
        full_range = f"{sheet_name or self.default_sheet_name}!{cell_range}"
        self._client.clear_range(full_range)

    def get_values_from_range(self, cell_range: str, sheet_name: str | None = None):
        full_range = f"{sheet_name or self.default_sheet_name}!{cell_range}"
        return self._client.get_values(full_range)
```

**Step 2: Update webhook sender to use `WebhookSender` with chunking**

Modify `/Users/alewando/Documents/Repo/dfs-workspace/nba_sheet/bot/discord.py`:
```python
from dfs_common.discord import WebhookSender

class Discord(BotInterface):
    def __init__(self, webhook):
        self._sender = WebhookSender(webhook, chunk_messages=True)

    def send_message(self, message):
        self._sender.send_message(message)
```

**Step 3: Run tests**

Run:
```bash
uv sync
uv run pytest -q
```
Expected: PASS

**Step 4: Commit**

Run:
```bash
git add services/google_sheets_service.py bot/discord.py
git commit -m "refactor: delegate nba_sheet sheets and discord to dfs-common"
```

---

### Task 6: Final verification

**Step 1: Run full test suite in each repo**

Run in each repo:
```bash
uv run pytest
```
Expected: PASS (note: `read_datagolf` may require `uv sync --extra dev` first)

**Step 2: Tag `dfs_common` (optional for future Option B)**

Run:
```bash
cd /Users/alewando/Documents/Repo/dfs-workspace/dfs_common
git tag v0.1.0
```
Expected: local tag created

**Step 3: Summary**

Document any intentional differences in each repo README.
