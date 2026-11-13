"""Shared fixtures for ContestDatabase persistence tests."""

import sqlite3
from collections.abc import Callable, Iterator
from typing import TypeVar, overload

import pytest
from persistence.builders import insert_contest

from dk_results.persistence.contestdatabase import ContestDatabase

_CursorT = TypeVar("_CursorT", bound=sqlite3.Cursor)


@pytest.fixture
def contest_db():
    db = ContestDatabase(":memory:")
    db.ensure_schema()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def contest_db_with_contest(contest_db):
    insert_contest(contest_db, dk_id=1)
    return contest_db


class FailingCursor(sqlite3.Cursor):
    """A cursor whose statements always fail with ``sqlite3.Error``."""

    def execute(self, *_args, **_kwargs):
        raise sqlite3.Error("boom")


class FailingConnection(sqlite3.Connection):
    """A real connection that hands out failing cursors and records rollbacks."""

    rolled_back = False

    @overload
    def cursor(self, factory: None = None) -> FailingCursor: ...
    @overload
    def cursor(self, factory: Callable[[sqlite3.Connection], _CursorT]) -> _CursorT: ...
    def cursor(self, factory=None):
        return (factory or FailingCursor)(self)

    def rollback(self):
        self.rolled_back = True
        super().rollback()


@pytest.fixture
def boom_conn() -> Iterator[FailingConnection]:
    conn = sqlite3.connect(":memory:", factory=FailingConnection)
    try:
        yield conn
    finally:
        conn.close()
