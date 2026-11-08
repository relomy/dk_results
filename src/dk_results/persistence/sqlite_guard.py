import functools
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, overload

if TYPE_CHECKING:
    from dk_results.persistence.contestdatabase import ContestDatabase


@overload
def _sqlite_guard[T](*, rollback: bool = False) -> Callable[[Callable[..., T]], Callable[..., T | None]]: ...


@overload
def _sqlite_guard[T](
    default_factory: Callable[[], T], *, rollback: bool = False
) -> Callable[[Callable[..., T]], Callable[..., T]]: ...


def _sqlite_guard[T](
    default_factory: Callable[[], T | None] = lambda: None, *, rollback: bool = False
) -> Callable[[Callable[..., T]], Callable[..., T | None]]:
    """Log and swallow ``sqlite3.Error`` from the wrapped method, returning
    ``default_factory()`` instead. Factors out the try/except-log shape used
    by the cash-line/VIP-status methods below (ADR-0011).

    Without a ``default_factory`` the swallowed error returns ``None``, so the
    decorated method is typed ``T | None``; with one it is typed ``T``."""

    def decorator(func: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(func)
        def wrapper(self: "ContestDatabase", *args: Any, **kwargs: Any) -> T | None:
            try:
                return func(self, *args, **kwargs)
            except sqlite3.Error:
                if rollback:
                    self.conn.rollback()
                self.logger.exception("sqlite error in %s()", getattr(func, "__name__", func))
                return default_factory()

        return wrapper

    return decorator
