"""Run the suites as if it were another day.

    FAKE_NOW=2026-12-31T23:30:00 PYTHONPATH=tests/clock_shim python tests/run_all.py --jobs auto

Python imports a module called sitecustomize at start-up, so putting this
directory on PYTHONPATH makes every test process (run_all starts each suite in
its own, inheriting the environment) believe it started at FAKE_NOW, a naive UTC
time. The clock then runs normally from there.

It exists because "passes today" says nothing about the last day of a month, a
leap day, the evening before a 1st or the night between two days in New York
(see .github/workflows/clock-check.yml, which runs it on a schedule). Several
suites that passed every day but a few turned out to depend on the date.

What it changes: datetime.datetime/.date now/utcnow/today, and time.time.
What it does not, and so can make a suite fail that is not wrong: the database's
own now() (PostgreSQL keeps real time, so a row stamped by the database sits
beside rows stamped by Python on another day), and anything in C that reads the
system clock directly (time.localtime, time.strftime with no argument,
monotonic clocks). A failure under a shifted clock is a lead to read, not a
verdict: run the suite on the real date too.

With FAKE_NOW unset this file does nothing at all.
"""
import os

spec = os.environ.get('FAKE_NOW')
if spec:
    import datetime as _dt
    import time as _t

    _real_dt, _real_date = _dt.datetime, _dt.date
    _offset = _real_dt.fromisoformat(spec) - _real_dt.utcnow()
    _real_time = _t.time

    # isinstance(x, datetime) must stay true for the real datetimes that drivers
    # and the standard library hand back, or code that checks types breaks.
    class _DTMeta(type):
        def __instancecheck__(cls, inst):
            return isinstance(inst, _real_dt)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, _real_dt)

    class _DateMeta(type):
        def __instancecheck__(cls, inst):
            return isinstance(inst, _real_date)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, _real_date)

    def _lift(d, cls):
        return cls(d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond, d.tzinfo)

    class FakeDatetime(_real_dt, metaclass=_DTMeta):
        @classmethod
        def now(cls, tz=None):
            return _lift(_real_dt.now(tz) + _offset, cls)

        @classmethod
        def utcnow(cls):
            return _lift(_real_dt.utcnow() + _offset, cls)

        @classmethod
        def today(cls):
            return cls.now()

    class FakeDate(_real_date, metaclass=_DateMeta):
        @classmethod
        def today(cls):
            n = _real_dt.now() + _offset
            return cls(n.year, n.month, n.day)

    _dt.datetime, _dt.date = FakeDatetime, FakeDate
    _t.time = lambda: _real_time() + _offset.total_seconds()
