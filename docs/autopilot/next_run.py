#!/usr/bin/env python3
"""Pick the autopilot's next wake-up time from usage, so no run starts that cannot work.

Plain arithmetic, no model call. Prints one ISO 8601 timestamp; --write also stores it in the wake file.
--gate reads that file at the start of a run: exit 0 means work, exit 3 means skip (Oct 14: unattended runs
cannot call update_scheduled_task, so an hourly cron fires and this file decides).
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone


def next_run(now, w, f, cap, weekly_reset, five_hour_reset, runnable, next_after=None):
    if w >= cap:  # weekly budget spent: sleep until it resets
        return weekly_reset + timedelta(minutes=10)
    if f >= 80:  # 5-hour window spent: sleep until it rolls over
        return max(five_hour_reset + timedelta(minutes=5), now + timedelta(minutes=15))
    if runnable:  # work left and budget left: continue soon
        return now + timedelta(minutes=15)
    if next_after:  # only date-gated tasks: wake on the earliest date
        return max(next_after, now + timedelta(hours=1))
    return now + timedelta(hours=6)  # nothing runnable: cheap check for new queue tasks


def gate(path, now):
    """True when a run should work: no wake file, an unreadable one, or its time has come."""
    try:
        with open(path) as fh:
            wake = datetime.fromisoformat(fh.read().strip())
    except (OSError, ValueError):
        return True
    return now >= wake


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gate", metavar="WAKE_FILE")
    p.add_argument("--write", metavar="WAKE_FILE")
    p.add_argument("--now", type=datetime.fromisoformat)
    p.add_argument("--w", type=float)
    p.add_argument("--f", type=float)
    p.add_argument("--cap", type=float, default=80)
    p.add_argument("--weekly-reset", type=datetime.fromisoformat)
    p.add_argument("--five-hour-reset", type=datetime.fromisoformat)
    p.add_argument("--runnable", type=int)
    p.add_argument("--next-after", type=datetime.fromisoformat)
    a = p.parse_args()
    if a.gate:
        if gate(a.gate, a.now or datetime.now(timezone.utc).astimezone()):
            print("RUN")
            sys.exit(0)
        print("SKIP")
        sys.exit(3)
    missing = [n for n in ("now", "w", "f", "weekly_reset", "five_hour_reset", "runnable") if getattr(a, n) is None]
    if missing:
        p.error("missing: " + ", ".join("--" + n.replace("_", "-") for n in missing))
    out = next_run(a.now, a.w, a.f, a.cap, a.weekly_reset, a.five_hour_reset, a.runnable, a.next_after).isoformat()
    if a.write:
        with open(a.write, "w") as fh:
            fh.write(out + "\n")
    print(out)
