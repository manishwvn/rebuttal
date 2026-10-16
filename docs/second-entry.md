# Second entry (E1)

Decision Oct 16, 2026: **go**. The Devpost rules ("Multiple Submissions") allow more than one submission if each is
unique and substantially different; each project can win up to one Grand or Honorable prize plus one Sponsor prize.

- Entry: **Mandate**, a buyer-side AI shopping agent that turns plain words into a spending mandate, searches a
  product catalog (Channel3), ranks options against the mandate in code, and checks out through the PayPal Orders v2
  sandbox only after the shopper approves. Separate repo `manishwvn/mandate` (private until Manish makes it public).
- Targets: Channel3 sponsor prize ($1,500) plus Most Creative or Best Use of Agentic Commerce. Bryntum dropped (trial
  is evaluation only and expires before judging ends).
- Shares no code, design, text or assets with Rebuttal.
- Its own routine `mandate-autopilot` runs hourly at :37 with lower caps (weekly 70%, 5-hour 60%) and skips while
  the Rebuttal autopilot holds its lock, so Rebuttal keeps priority.
