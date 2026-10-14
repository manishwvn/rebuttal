#!/usr/bin/env python3
"""Pick the autopilot's next wake-up time from usage, so no run starts that cannot work.

Plain arithmetic, no model call. Prints one ISO 8601 timestamp for update_scheduled_task fireAt.
"""
import argparse
from datetime import datetime, timedelta


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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--now", type=datetime.fromisoformat, required=True)
    p.add_argument("--w", type=float, required=True)
    p.add_argument("--f", type=float, required=True)
    p.add_argument("--cap", type=float, default=80)
    p.add_argument("--weekly-reset", type=datetime.fromisoformat, required=True)
    p.add_argument("--five-hour-reset", type=datetime.fromisoformat, required=True)
    p.add_argument("--runnable", type=int, required=True)
    p.add_argument("--next-after", type=datetime.fromisoformat)
    a = p.parse_args()
    print(next_run(a.now, a.w, a.f, a.cap, a.weekly_reset, a.five_hour_reset, a.runnable, a.next_after).isoformat())
