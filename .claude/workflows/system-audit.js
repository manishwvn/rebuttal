export const meta = {
  name: 'system-audit',
  description: 'Daily whole-system audit of Rebuttal: one Sonnet reviewer per component, a fresh-clone run-from-README check, an Opus principal engineer who verifies findings and turns them into queue tasks',
  whenToUse: 'Once a day from the autopilot (docs/autopilot/CYCLE.md), on main. Read-only; returns verified issues for the lead to add to QUEUE.md.',
  phases: [
    { title: 'Component review', detail: 'Sonnet reviewer per component, read-only', model: 'sonnet' },
    { title: 'Fresh clone', detail: 'Follow README and frontend/README from a clean clone, mock mode', model: 'sonnet' },
    { title: 'Principal', detail: 'Opus verifies every finding, adds cross-cutting issues, writes queue tasks', model: 'opus' },
  ],
}

// args: { sha, scratch }  sha = commit of main being audited; scratch = absolute path of an empty scratch directory.

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' }, line: { type: 'integer' },
          severity: { type: 'string', enum: ['blocker', 'should_fix', 'nit'] },
          problem: { type: 'string' }, evidence: { type: 'string', description: 'command output or code quote that proves it' },
          fix: { type: 'string' },
        },
        required: ['file', 'severity', 'problem', 'evidence', 'fix'],
      },
    },
  },
  required: ['findings'],
}

const TASKS = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: '3 plain-English sentences on the health of the system' },
    critical: { type: 'boolean', description: 'true if anything needs Manish or is a live safety / secret / money problem' },
    tasks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          size: { type: 'string', enum: ['S', 'M', 'L'] },
          priority: { type: 'string', enum: ['now', 'next', 'later'] },
          spec: { type: 'string', description: 'queue-ready task text with acceptance criteria and the evidence' },
        },
        required: ['title', 'size', 'priority', 'spec'],
      },
    },
    rejected: { type: 'array', items: { type: 'string' }, description: 'findings judged wrong, one line each' },
  },
  required: ['summary', 'critical', 'tasks', 'rejected'],
}

const sha = (args && args.sha) || 'origin/main'
const scratch = args && args.scratch
const READ = `Read-only audit of the Rebuttal repo at /Users/manish/Documents/rebuttal, commit ${sha} (use git show ${sha}:<path> or read the main checkout if it is at that commit). Never edit, commit or push. Never read or print backend/.env values. Skip vendored .claude/skills and .agents.`

const COMPONENTS = [
  { key: 'agent', scope: 'backend/rebuttal/agent/ (graph, facts, reasoner + guard, llm, pipeline), backend/rebuttal/store.py, policies.py, scenarios.py, backend/evals/', ask: 'Facts computed in code and correct for every dispute reason; guard rules consistent with the facts; model output validated; prompts not leaking data; eval runner honest (held-out sets not tuned on).' },
  { key: 'paypal-approval', scope: 'backend/rebuttal/approval.py, backend/rebuttal/paypal/ (client, mock), config.py, persistence.py, audit.py', ask: 'Only execute writes to PayPal and only after a human decision; read_only() client really refuses non-GET; PayPal-Request-Id deterministic; nothing fallible after interrupt() returns or after the PayPal call; mock mirrors the real sandbox (VERIFY notes); sandbox-only guard; audit log complete. Run tests/test_write_boundary.py and tests/test_core.py.' },
  { key: 'api', scope: 'backend/rebuttal/app.py, runtime.py, tracing.py, backend/tests/', ask: 'Every /api route protected except health and the signed webhook; webhook signature verification; error handling and status codes; CORS; mock-only endpoints refuse in sandbox mode; tests cover each route; run the full pytest suite.' },
  { key: 'frontend', scope: 'frontend/ (src, e2e, configs)', ask: 'Field names match the backend payloads; every write goes through a confirm step; no token in the bundle; loading/error/empty states; accessibility basics; run npm ci, npm run lint, npm run build, npx playwright test.' },
  { key: 'ops-docs', scope: 'render.yaml, .github/workflows/, backend/.env.example, README.md, STATUS.md, PLAN.md, docs/, CLAUDE.md, docs/autopilot/', ask: 'Deploy config builds and starts what the code needs; every env var the code reads is in .env.example and render.yaml (or documented); CI covers backend and frontend; docs claims match the code (commands, numbers, features marked done); live health https://rebuttal-oq3g.onrender.com/api/health answers ok.' },
]

phase('Component review')
const reviews = parallel(COMPONENTS.map(c => () => agent(`${READ}
You are the independent reviewer for the "${c.key}" component: ${c.scope}.
${c.ask}
Also look for the basic things that get missed: code that was never run, claims in comments or docs that are false, missing tests for a behavior, inconsistencies with the other components it talks to.
Report only real problems, each with evidence (a command and its output, or a code quote) and the exact fix.`,
  { label: `component:${c.key}`, phase: 'Component review', agentType: 'reviewer', model: 'sonnet', effort: 'high', schema: FINDINGS })
  .then(r => r && { component: c.key, findings: r.findings })))

const cloneCheck = scratch ? agent(`Fresh-eyes check of Rebuttal as a new developer or a hackathon judge would do it. Work only inside ${scratch}.
1. git clone https://github.com/manishwvn/rebuttal.git ${scratch}/rebuttal && cd ${scratch}/rebuttal && git checkout ${sha}
2. Follow README.md and frontend/README.md literally, in mock mode only (REBUTTAL_MOCK=1, REBUTTAL_REASONER=rules, no keys, no .env from anywhere else). Start the backend and the dashboard as documented, run the hero case through the simulator, approve it, and check the audit trail. Use ports that are free (check with lsof first) and stop every process you started at the end.
3. Report every step where the docs are wrong, missing, or the app fails, with the exact command and output. Do not fix anything. Never use a model key or the real sandbox.`,
  { label: 'fresh-clone', phase: 'Fresh clone', model: 'sonnet', effort: 'high', schema: FINDINGS })
  .then(r => r && { component: 'fresh-clone', findings: r.findings }) : Promise.resolve(null)

const found = (await Promise.all([reviews, cloneCheck])).flat().filter(Boolean)
const total = found.reduce((n, r) => n + r.findings.length, 0)
log(`${total} raw findings from ${found.length} reviewers`)

phase('Principal')
const decision = await agent(`${READ}
You are the Opus principal engineer. Independent reviewers audited each component of Rebuttal and a fresh clone was run from the README. Their findings:
${JSON.stringify(found, null, 2)}

1. Verify every blocker and should_fix against the code or by running the command yourself. Put wrong ones in rejected (one line each, why).
2. Look across components for what no single reviewer could see: contract mismatches between backend and frontend, config vs code drift, docs vs reality, gaps in the safety story (single write path, approval gate, guard, audit), anything a judge would hit in the first minute.
3. Turn the confirmed issues into queue-ready tasks (group related fixes; each with acceptance criteria and the evidence). Priority now = safety, secrets, money, broken main, broken live service or broken judge path.
critical = true only for a live safety, secret or money problem, or something only Manish can fix.`,
  { label: 'principal', phase: 'Principal', agentType: 'reviewer', model: 'opus', effort: 'high', schema: TASKS })

return { sha, raw_findings: total, ...decision }
