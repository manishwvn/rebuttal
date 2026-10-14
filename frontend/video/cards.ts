/**
 * Static cards for the demo video. Each export returns a complete, self-contained
 * HTML document for Playwright page.setContent() at 1280x720: no network, no
 * external fonts or images, inline <style> only. The bottom 110 px of every card
 * stay empty because a caption bar is overlaid there.
 */

const INK = "#14202e";
const ACCENT = "#0e6b63";
const BACKGROUND = "#f2f5f8";
const BORDER = "#d5dde6";
const SANS = "'Public Sans', system-ui, -apple-system, sans-serif";
const MONO = "'JetBrains Mono', ui-monospace, Menlo, monospace";

const TERMINAL_BG = "#0f1720";
const TERMINAL_BAR = "#1b2735";
const TERMINAL_DOT = "#3a4756";
const TERMINAL_TEXT = "#d7e0ea";
const TERMINAL_PASS = "#5fd38d";
const TERMINAL_FAIL = "#ff7b72";
const TERMINAL_PROMPT =
  '$ cd backend && uv run pytest tests/test_write_boundary.py "tests/test_core.py::test_analyze_never_writes_to_paypal" -v';
const TERMINAL_TAIL_LINES = 20;

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

/** Shared shell: 1280x720 page, a 610 px stage, and an empty 110 px strip at the bottom. */
function page(title: string, css: string, body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>
html, body { margin: 0; width: 1280px; height: 720px; overflow: hidden; }
body { background: ${BACKGROUND}; color: ${INK}; font-family: ${SANS}; }
.stage { box-sizing: border-box; width: 1280px; height: 610px; padding: 48px 64px 24px; display: flex; flex-direction: column; overflow: hidden; }
.content { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; }
h1 { margin: 0 0 40px; font-size: 48px; line-height: 1.15; font-weight: 700; }
p { margin: 0; }
.footer { font-size: 20px; opacity: 0.7; }
.panel { box-sizing: border-box; background: #ffffff; border: 1px solid ${BORDER}; border-radius: 10px; padding: 28px 32px; }
${css}
</style>
</head>
<body>
<main class="stage">
${body}
</main>
</body>
</html>`;
}

const PIPELINE_STEPS: ReadonlyArray<{ readonly text: string; readonly cls: string }> = [
  { text: "gather (read-only GET)", cls: "" },
  { text: "decide (the only model call)", cls: "" },
  { text: "guard", cls: "" },
  { text: "plan one action", cls: "" },
  { text: "human approves, edits or rejects", cls: "human" },
  { text: "execute (the only PayPal writes)", cls: "last" },
];

export function pipelineCard(): string {
  const boxes = PIPELINE_STEPS.map(
    (step) => `<div class="box ${step.cls}">${escapeHtml(step.text)}</div>`,
  );
  const flow = boxes.join('\n<span class="arrow">&rarr;</span>\n');
  const css = `
.flow { display: flex; align-items: stretch; margin: auto 0; }
.box { flex: 1 1 0; min-width: 0; min-height: 170px; box-sizing: border-box; display: flex; align-items: center; justify-content: center; text-align: center; background: #ffffff; border: 1px solid ${BORDER}; border-radius: 10px; padding: 16px 12px; font-size: 26px; line-height: 1.25; }
.box.human { border: 5px solid ${INK}; }
.box.last { background: ${ACCENT}; border-color: ${ACCENT}; color: #ffffff; }
.arrow { flex: 0 0 28px; display: flex; align-items: center; justify-content: center; font-size: 30px; }`;
  const body = `<section class="content">
<h1>${escapeHtml("How a dispute moves through Rebuttal")}</h1>
<div class="flow">
${flow}
</div>
</section>
<p class="footer">${escapeHtml("Source: backend/rebuttal/agent/graph.py")}</p>`;
  return page("How a dispute moves through Rebuttal", css, body);
}

const PROOF_STEPS: ReadonlyArray<{ readonly text: string; readonly cls: string }> = [
  { text: "Buyer files a dispute in the PayPal sandbox", cls: "" },
  {
    text: "Signed webhook CUSTOMER.DISPUTE.CREATED arrives (about 4 minutes later), signature verified",
    cls: "wide",
  },
  { text: "gather, decide, guard, propose (reads only)", cls: "" },
  { text: "Paused at the approval gate", cls: "last" },
];

export function liveProofCard(): string {
  const boxes = PROOF_STEPS.map(
    (step) => `<div class="box ${step.cls}">${escapeHtml(step.text)}</div>`,
  );
  const flow = boxes.join('\n<span class="arrow">&rarr;</span>\n');
  const css = `
.sub { font-size: 26px; line-height: 1.35; margin: 0 0 56px; }
.flow { display: flex; align-items: stretch; margin: auto 0; }
.box { flex: 1 1 0; min-width: 0; min-height: 170px; box-sizing: border-box; display: flex; align-items: center; justify-content: center; text-align: center; background: #ffffff; border: 1px solid ${BORDER}; border-radius: 10px; padding: 16px 12px; font-size: 24px; line-height: 1.25; }
.box.wide { flex-grow: 1.6; }
.box.last { background: ${ACCENT}; border-color: ${ACCENT}; color: #ffffff; }
.arrow { flex: 0 0 28px; display: flex; align-items: center; justify-content: center; font-size: 30px; }`;
  const body = `<!-- Facts from STATUS.md (Webhook proven live, Hero case correct live); no live call made for the video. -->
<section class="content">
<h1>${escapeHtml("Proof on the real PayPal sandbox")}</h1>
<p class="sub">${escapeHtml(
    "Rebuttal on Render, October 7, 2026. Dispute PP-R-SVN-10190455, filed by a buyer account.",
  )}</p>
<div class="flow">
${flow}
</div>
</section>
<p class="footer">${escapeHtml("PayPal writes before approval: 0")}</p>`;
  return page("Proof on the real PayPal sandbox", css, body);
}

function trimTrailingBlank(lines: string[]): string[] {
  let end = lines.length;
  while (end > 0 && lines[end - 1].trim() === "") {
    end--;
  }
  return lines.slice(0, end);
}

function renderTerminalLine(line: string): string {
  const text = escapeHtml(line);
  if (line.includes("FAILED") || line.includes("ERROR")) {
    return `<span class="fail">${text}</span>`;
  }
  if (line.includes(" PASSED") || line.includes(" passed")) {
    return `<span class="pass">${text}</span>`;
  }
  return text;
}

export function terminalCard(output: string): string {
  const lines = trimTrailingBlank(output.split(/\r?\n/)).slice(-TERMINAL_TAIL_LINES);
  const screen = [
    `<span class="prompt">${escapeHtml(TERMINAL_PROMPT)}</span>`,
    ...lines.map(renderTerminalLine),
  ].join("\n");
  const css = `
.stage { padding: 24px 64px; }
.window { flex: 1; min-height: 0; display: flex; flex-direction: column; background: ${TERMINAL_BG}; border-radius: 10px; overflow: hidden; }
.bar { flex: 0 0 36px; display: flex; align-items: center; gap: 10px; padding: 0 16px; background: ${TERMINAL_BAR}; }
.bar span { width: 12px; height: 12px; border-radius: 50%; background: ${TERMINAL_DOT}; }
.screen { flex: 1; min-height: 0; margin: 0; padding: 12px 24px; overflow: hidden; color: ${TERMINAL_TEXT}; font-family: ${MONO}; font-size: 20px; line-height: 22px; white-space: pre; }
.prompt { white-space: pre-wrap; overflow-wrap: anywhere; }
.pass { color: ${TERMINAL_PASS}; }
.fail { color: ${TERMINAL_FAIL}; }`;
  const body = `<section class="content">
<div class="window">
<div class="bar"><span></span><span></span><span></span></div>
<pre class="screen">${screen}</pre>
</div>
</section>`;
  return page("Terminal", css, body);
}

export function evalCard(stage: 1 | 2): string {
  const mainSet =
    stage === 2
      ? `<section class="panel main">
<p>${escapeHtml(
          "Main set, 20 cases we tuned on: rules only 85% (hard cases 1 of 4); model + guard (Groq qwen/qwen3.8-27b) 95% (19 of 20), hard cases 4 of 4.",
        )}</p>
<div class="chips">
<span class="chip">${escapeHtml("85-95% across three Groq runs.")}</span>
<span class="chip">${escapeHtml("4 hard cases = the buyer's wording changes the right answer.")}</span>
</div>
</section>`
      : "";
  const css = `
.statement { font-size: 44px; line-height: 1.25; font-weight: 600; }
.main { margin-top: 40px; }
.main p { font-size: 28px; line-height: 1.35; }
.chips { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 24px; }
.chip { background: ${ACCENT}; color: #ffffff; border-radius: 999px; padding: 10px 22px; font-size: 24px; }`;
  const body = `<!-- Numbers come from backend/evals/RESULTS.md and docs/video-script.md section 4.3. -->
<section class="content">
<h1>${escapeHtml("Held-out test")}</h1>
<p class="statement">${escapeHtml(
    "10 unseen disputes, never used for tuning: model alone 8 of 10, model + guard 10 of 10",
  )}</p>
${mainSet}
</section>
<p class="footer">${escapeHtml("PayPal writes before approval: 0")}</p>`;
  return page("Held-out test", css, body);
}

export function closeCard(stage: 1 | 2): string {
  const content =
    stage === 1
      ? `<h1 class="big">${escapeHtml("The agent does the digging. The merchant makes the call.")}</h1>
<p class="order">${escapeHtml(
          "$48 order, AI assistant ordered L, told M: refund after return, the right item promised, approved after one confirm.",
        )}</p>`
      : `<div class="cols">
<section class="panel">
<h2>${escapeHtml("Real")}</h2>
<p>${escapeHtml("PayPal sandbox API, signed webhooks, Render, held-out eval.")}</p>
</section>
<section class="panel">
<h2>${escapeHtml("Demo")}</h2>
<p>${escapeHtml("Mock sandbox, seeded orders. Sandbox only: no live money.")}</p>
</section>
</div>
<p class="link">${escapeHtml("github.com/manishwvn/rebuttal, MIT licence")}</p>
<p class="credits">${escapeHtml("PayPal APIs · LangGraph · AG Grid · Render · Supabase · Langfuse")}</p>`;
  const css = `
h1.big { font-size: 52px; line-height: 1.15; margin-bottom: 40px; }
.order { font-size: 28px; line-height: 1.35; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.cols h2 { margin: 0 0 16px; font-size: 40px; line-height: 1.15; }
.cols p { font-size: 28px; line-height: 1.35; }
.link { margin-top: 40px; font-size: 28px; }
.credits { margin-top: 20px; font-size: 20px; opacity: 0.7; }`;
  const body = `<section class="content">
${content}
</section>`;
  return page("Close", css, body);
}
