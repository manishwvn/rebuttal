#!/usr/bin/env python3
"""Project completion percent from docs/autopilot/QUEUE.md. Plain parsing, no model call.

Every `### <id> <title> — size S|M|L — <status>` heading counts, weighted S=1, M=3, L=8. Headings without a size are
milestones (freeze, reminders) and do not count. Status credit: `superseded` drops the task; `in progress` 0.5 and
`in review` 0.8 unless the status holds an explicit `[NN%]`; `done` or `merged` 1.0; anything else 0. 100% means
every task, including D5 (submitted on Devpost), is done.
"""
import re
import sys
from datetime import date
from pathlib import Path

WEIGHT = {"S": 1, "M": 3, "L": 8}
HEAD = re.compile(r"^### (\S+) .*? — size ([SML]) — (.*)$")
SUBMIT = date(2026, 11, 10)


def credit(status):
    s = status.lower()
    if "superseded" in s:
        return None
    explicit = re.search(r"\[(\d{1,3})%\]", s)
    if explicit:
        return min(int(explicit.group(1)), 100) / 100
    if s.startswith("in progress"):
        return 0.5
    if s.startswith("in review"):
        return 0.8
    if re.match(r"(done|merged)\b", s):  # only a status that starts with done/merged
        return 1.0
    return 0.0


def progress(text):
    total = earned = 0.0
    done = count = 0
    for line in text.splitlines():
        m = HEAD.match(line)
        if not m:
            continue
        c = credit(m.group(3))
        if c is None:
            continue
        w = WEIGHT[m.group(2)]
        total += w
        earned += w * c
        count += 1
        done += c == 1.0
    return round(100 * earned / total) if total else 0, done, count


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("QUEUE.md")
    pct, done, count = progress(path.read_text())
    days = (SUBMIT - date.today()).days
    print(f"progress {pct}% ({done}/{count} tasks done, {days} days to Nov 10 submit)")
