"""The demo video shot list (frontend/video/shots.json) stays in step with the narration in docs/video-script.md."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS_PATH = ROOT / "frontend" / "video" / "shots.json"
SCRIPT_PATH = ROOT / "docs" / "video-script.md"

IDS = [
    "hook",
    "open",
    "analyze",
    "mismatch",
    "facts",
    "decision",
    "guard",
    "edit",
    "confirm",
    "approved",
    "safety-graph",
    "safety-tests",
    "eval-held-out",
    "eval-main",
    "close-pitch",
    "close-real",
]


def _shots():
    return json.loads(SHOTS_PATH.read_text(encoding="utf-8"))["shots"]


def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def _script_section_7():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    start = text.index("## 7. Narration only")
    start = text.index("\n", start) + 1
    end = text.find("## 8.", start)
    return _collapse(text[start:] if end == -1 else text[start:end])


def test_ids_are_the_sixteen_shots_in_order():
    ids = [shot["id"] for shot in _shots()]
    assert ids == IDS
    assert len(set(ids)) == len(ids)


def test_every_shot_has_narration_and_a_positive_minimum():
    for shot in _shots():
        assert shot["narration"].strip(), shot["id"]
        assert shot["minSeconds"] > 0, shot["id"]


def test_total_minimum_time_is_151_seconds_under_three_minutes():
    total = sum(shot["minSeconds"] for shot in _shots())
    assert total == 151
    assert total < 180


def test_badge_is_on_exactly_the_first_ten_shots():
    badges = [shot["badge"] for shot in _shots()]
    assert badges == [True] * 10 + [False] * 6


def test_only_the_hook_shot_has_a_tag():
    tagged = [shot["id"] for shot in _shots() if "tag" in shot]
    assert tagged == ["hook"]


def test_narration_matches_section_7_of_the_script():
    section = _script_section_7()
    for shot in _shots():
        spoken = _collapse(shot.get("scriptText") or shot["narration"])
        assert spoken in section, shot["id"]


def test_only_the_decision_shot_has_script_text():
    with_script_text = [shot["id"] for shot in _shots() if "scriptText" in shot]
    assert with_script_text == ["decision"]


def test_no_narration_mentions_ag_studio():
    for shot in _shots():
        assert "AG Studio" not in shot["narration"], shot["id"]
