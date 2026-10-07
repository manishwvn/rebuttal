"""Inject preview_data.json into preview/template.html -> preview/rebuttal-preview.html.

    cd backend && python -m evals.run && python -m scripts.demo && python -m scripts.build_preview
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
data = (ROOT / "backend" / "preview_data.json").read_text()
template = (ROOT / "preview" / "template.html").read_text()
out = ROOT / "preview" / "rebuttal-preview.html"
out.write_text(template.replace("/*__DATA__*/null", data.replace("</", "<\\/")))
print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
