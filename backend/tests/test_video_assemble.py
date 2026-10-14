"""video_assemble: SRT, length limit, ffmpeg argv, and narrate/assemble with a fake subprocess (no say, no ffmpeg)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import video_assemble as va

SHOTS = {
    "shots": [
        {"id": "intro", "minSeconds": 5.0, "narration": "Meet the dispute."},
        {"id": "agent", "minSeconds": 1.0, "narration": "The agent reads the order."},
    ]
}
SAY_VOICES = "Samantha            en_US    # Hello! My name is Samantha.\nAlex                en_US    # Hello.\n"


class FakeRun:
    """Stands in for subprocess.run: answers `say -v ?` and ffprobe, records every argv."""

    def __init__(self, probe: str = "2.5\n") -> None:
        self.probe = probe
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        stdout = ""
        if argv == ["say", "-v", "?"]:
            stdout = SAY_VOICES
        elif argv[0] == "ffprobe":
            stdout = self.probe
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def write_shots(tmp_path: Path) -> Path:
    path = tmp_path / "shots.json"
    path.write_text(json.dumps(SHOTS), encoding="utf-8")
    return path


def write_timeline(work: Path, timeline: list[dict[str, Any]]) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")


TIMELINE = [
    {"id": "intro", "startMs": 1000, "endMs": 4000},
    {"id": "agent", "startMs": 4000, "endMs": 7500},
]


@pytest.mark.parametrize(
    ("min_seconds", "narration_ms", "expected"),
    [(5.0, 2000, 5000), (1.0, 2500, 3500)],
)
def test_hold_ms_takes_the_longer_of_minimum_and_narration_plus_pad(min_seconds, narration_ms, expected):
    assert va.hold_ms(min_seconds, narration_ms) == expected


@pytest.mark.parametrize(("ms", "text"), [(0, "00:00:00,000"), (3661250, "01:01:01,250")])
def test_srt_time_formats_hours_minutes_seconds_millis(ms, text):
    assert va.srt_time(ms) == text


def test_build_srt_starts_cues_at_first_timeline_start():
    timeline = [
        {"id": "intro", "startMs": 1500, "endMs": 4000},
        {"id": "agent", "startMs": 4000, "endMs": 9250},
    ]
    srt = va.build_srt(SHOTS["shots"], timeline)
    assert srt == (
        "1\n00:00:00,000 --> 00:00:02,500\nMeet the dispute.\n"
        "\n"
        "2\n00:00:02,500 --> 00:00:07,750\nThe agent reads the order.\n"
    )


def test_check_length_accepts_under_limit_and_rejects_limit():
    va.check_length(179.9)
    with pytest.raises(ValueError, match="180"):
        va.check_length(180)


def test_build_ffmpeg_cmd_for_three_shots(tmp_path):
    work = tmp_path / "work"
    out = tmp_path / "out.mp4"
    shots = [{"id": s, "minSeconds": 1.0, "narration": s} for s in ("a", "b", "c")]
    timeline = [
        {"id": "a", "startMs": 1000, "endMs": 3000},
        {"id": "b", "startMs": 3000, "endMs": 6000},
        {"id": "c", "startMs": 6000, "endMs": 9000},
    ]
    cmd = va.build_ffmpeg_cmd(work, out, shots, timeline)
    text = " ".join(cmd)

    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "1.000"
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-i") + 1] == str(work / "screen.webm")
    inputs = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-i"]
    assert inputs == [
        str(work / "screen.webm"),
        str(work / "audio" / "a.aiff"),
        str(work / "audio" / "b.aiff"),
        str(work / "audio" / "c.aiff"),
        str(work / "rebuttal-demo.srt"),
    ]
    assert cmd[cmd.index("-filter_complex") + 1] == (
        "[1:a]adelay=0:all=1[a1];[2:a]adelay=2000:all=1[a2];[3:a]adelay=5000:all=1[a3];"
        "[a1][a2][a3]amix=inputs=3:normalize=0:duration=longest[aout]"
    )
    assert "-map 0:v -map [aout] -map 4:s" in text
    assert "-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -c:s mov_text" in text
    assert cmd[cmd.index("-t") + 1] == "8.000"
    assert cmd[-1] == str(out)
    assert all(isinstance(arg, str) for arg in cmd)


def test_narrate_writes_audio_and_durations(tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(va.subprocess, "run", fake)
    work = tmp_path / "work"

    va.narrate(write_shots(tmp_path), work, "Samantha")

    intro, agent = str(work / "audio" / "intro.aiff"), str(work / "audio" / "agent.aiff")
    assert (work / "audio").is_dir()
    assert ["say", "-v", "Samantha", "-o", intro, "--", "Meet the dispute."] in fake.calls
    assert ["say", "-v", "Samantha", "-o", agent, "--", "The agent reads the order."] in fake.calls
    probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", intro]
    assert probe in fake.calls
    durations = json.loads((work / "durations.json").read_text(encoding="utf-8"))
    assert durations == {
        "intro": {"narrationMs": 2500, "holdMs": 5000},
        "agent": {"narrationMs": 2500, "holdMs": 3500},
    }


def test_narrate_unknown_voice_exits_before_speaking(tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(va.subprocess, "run", fake)

    with pytest.raises(SystemExit) as exc:
        va.narrate(write_shots(tmp_path), tmp_path / "work", "Nobody")

    assert "VIDEO_VOICE" in str(exc.value) and "say -v ?" in str(exc.value)
    assert fake.calls == [["say", "-v", "?"]]


def test_narrate_without_say_exits_clearly(tmp_path, monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(va.subprocess, "run", missing)

    with pytest.raises(SystemExit, match="say not found"):
        va.narrate(write_shots(tmp_path), tmp_path / "work", "Samantha")


def test_narrate_without_ffprobe_exits_with_install_hint(tmp_path, monkeypatch):
    base = FakeRun()

    def no_ffprobe(argv, **kwargs):
        if argv[0] == "ffprobe":
            raise FileNotFoundError(argv[0])
        return base(argv, **kwargs)

    monkeypatch.setattr(va.subprocess, "run", no_ffprobe)

    with pytest.raises(SystemExit, match="brew install ffmpeg"):
        va.narrate(write_shots(tmp_path), tmp_path / "work", "Samantha")


@pytest.mark.parametrize(("env", "voice"), [("Alex", "Alex"), (None, "Samantha")])
def test_narrate_voice_defaults_to_env_then_samantha(tmp_path, monkeypatch, env, voice):
    fake = FakeRun()
    monkeypatch.setattr(va.subprocess, "run", fake)
    if env is None:
        monkeypatch.delenv("VIDEO_VOICE", raising=False)
    else:
        monkeypatch.setenv("VIDEO_VOICE", env)

    va.main(["narrate", "--shots", str(write_shots(tmp_path)), "--work", str(tmp_path / "work")])

    say_voices = {call[2] for call in fake.calls if call[0] == "say" and call[1] == "-v" and call[2] != "?"}
    assert say_voices == {voice}


def test_assemble_rejects_mismatched_ids(tmp_path):
    work = tmp_path / "work"
    write_timeline(work, [
        {"id": "agent", "startMs": 0, "endMs": 1000},
        {"id": "intro", "startMs": 1000, "endMs": 2000},
    ])

    with pytest.raises(ValueError, match="ids"):
        va.assemble(write_shots(tmp_path), work, tmp_path / "out.mp4")


def test_assemble_rejects_timeline_of_180_seconds_or_more(tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(va.subprocess, "run", fake)
    work = tmp_path / "work"
    write_timeline(work, [
        {"id": "intro", "startMs": 0, "endMs": 90000},
        {"id": "agent", "startMs": 90000, "endMs": 180000},
    ])

    with pytest.raises(ValueError, match="180"):
        va.assemble(write_shots(tmp_path), work, tmp_path / "out.mp4")
    assert fake.calls == []
    assert not (work / "rebuttal-demo.srt").exists()


def test_assemble_writes_srt_and_runs_ffmpeg_once(tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(va.subprocess, "run", fake)
    work = tmp_path / "work"
    write_timeline(work, TIMELINE)
    out = tmp_path / "deep" / "rebuttal-demo.mp4"

    seconds = va.assemble(write_shots(tmp_path), work, out)

    assert seconds == 6.5
    assert (work / "rebuttal-demo.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:03,000\nMeet the dispute.\n"
        "\n"
        "2\n00:00:03,000 --> 00:00:06,500\nThe agent reads the order.\n"
    )
    assert out.parent.is_dir()
    ffmpeg_calls = [call for call in fake.calls if call[0] == "ffmpeg"]
    assert len(ffmpeg_calls) == 1
    assert ffmpeg_calls[0][-1] == str(out)


def test_assemble_without_ffmpeg_exits_with_install_hint(tmp_path, monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(va.subprocess, "run", missing)
    work = tmp_path / "work"
    write_timeline(work, TIMELINE)

    with pytest.raises(SystemExit, match="ffmpeg not found: brew install ffmpeg"):
        va.assemble(write_shots(tmp_path), work, tmp_path / "out.mp4")


def test_main_assemble_prints_written_path_and_length(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(va.subprocess, "run", FakeRun())
    work = tmp_path / "work"
    write_timeline(work, TIMELINE)
    out = tmp_path / "rebuttal-demo.mp4"

    va.main(["assemble", "--shots", str(write_shots(tmp_path)), "--work", str(work), "--out", str(out)])

    assert capsys.readouterr().out == f"Wrote {out} (6.500 s)\n"
