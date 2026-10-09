# Autopilot

Rebuttal is finished by an unattended lead-dev session, not by hand-written prompts.

- **When:** a Claude desktop scheduled task (`rebuttal-autopilot`) every 3 hours, while the Mac is on, plugged in,
  awake and the Claude app is open. A missed run happens on the next launch.
- **What each cycle does:** `CYCLE.md`: lock, usage guard, 1-3 tasks from `QUEUE.md` (by usage headroom), each in its own
  git worktree, run by the `team-cycle` workflow: Opus lead -> Sonnet tech lead per task -> parallel Haiku workers
  (xhigh / max effort) -> Sonnet integration and PR -> reviewer (Opus for PayPal paths). The lead merges and logs.
- **Budget:** stops at 80% weekly usage (Manish's hard line is 85%); pauses when the 5-hour window is above 85%. Rate limits and Groq quota errors just wait for the next cycle. No money is ever spent.
- **Alerts:** phone push plus an email (an issue in the private repo `manishwvn/rebuttal-alerts` that @mentions
  Manish), only for weekly usage at 80%, things only Manish can do, or real breakage.
- **Progress:** `LOG.md` (daily summary at the top), `QUEUE.md` statuses, `STATUS.md`.
