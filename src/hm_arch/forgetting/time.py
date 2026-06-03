"""Injectable time source for deterministic lifecycle tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class TimeProvider:
    """Return the current UTC time for retention and lifecycle scheduling."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        raise NotImplementedError


class SystemTimeProvider(TimeProvider):
    """Production time source backed by the system clock."""

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)


class ManualTimeProvider(TimeProvider):
    """Controllable clock for offline lifecycle tests.

    Tests advance time with :meth:`advance` instead of sleeping or mutating
    stored timestamps.
    """

    def __init__(self, start: datetime | None = None) -> None:
        if start is None:
            self._now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        else:
            self._now = start if start.tzinfo is not None else start.replace(
                tzinfo=timezone.utc
            )

    def now(self) -> datetime:
        return self._now

    def advance(self, *, hours: float = 0.0, days: float = 0.0) -> datetime:
        """Move the clock forward and return the new instant."""
        self._now = self._now + timedelta(hours=hours, days=days)
        return self._now

    def set(self, moment: datetime) -> None:
        """Set the clock to an explicit instant."""
        self._now = moment if moment.tzinfo is not None else moment.replace(
            tzinfo=timezone.utc
        )
