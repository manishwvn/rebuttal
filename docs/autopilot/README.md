# Autopilot

Rebuttal is finished by an unattended lead-dev session, not by hand-written prompts.

- **When:** a Claude desktop scheduled task (`rebuttal-autopilot`) every 3 hours, while the Mac is on, plugged in,
  awake and the Claude app is open. A missed run happens on the next launch.
- **What each cycle does:** `CYCLE.md`: lock, usage guard, 1-3 tasks from `QUEUE.md` (by usage headroom), each in its own
  git worktree, run by the `team-cycle` workflow: Opus lead -> Sonnet tech lead per task -> Haiku fleet
  (xhigh / max effort, 3 Haiku auditors per piece) -> Sonnet integration and PR -> review panel (3 Sonnet reviewers, then an Opus principal engineer who verifies
  every finding and decides). The lead merges and logs. Once a day the `system-audit` workflow reviews every component,
  runs the project from a fresh clone by its README, and an Opus principal turns verified issues into queue tasks.
- **Budget:** stops at 80% weekly usage (Manish's hard line is 85%); pauses when the 5-hour window is above 85%. Rate limits and Groq quota errors just wait for the next cycle. No money is ever spent.
- **Alerts:** phone push plus an email (an issue in the private repo `manishwvn/rebuttal-alerts` that @mentions
  Manish), only for weekly usage at 80%, things only Manish can do, or real breakage.
- **Progress:** `LOG.md` (daily summary at the top), `QUEUE.md` statuses, `STATUS.md`.
