"""Narrate the demo shots and assemble the recording into the final video.

    cd backend && uv run python -m scripts.video_assemble narrate \
        --shots ../frontend/video/shots.json --work ../media/work
    cd backend && uv run python -m scripts.video_assemble assemble \
        --shots ../frontend/video/shots.json --work ../media/work --out ../media/rebuttal-demo.mp4

narrate: `say` writes audio/<id>.aiff for each shot (voice: --voice, else env VIDEO_VOICE, else Samantha; `say -v ?`
lists them), ffprobe measures each clip, and durations.json gets the narration and hold lengths the recorder reads.
assemble: checks timeline.json (written by the recorder) against the shots, writes rebuttal-demo.srt, and muxes the
screen recording, the narration and the subtitles with ffmpeg. The video must stay under 180 s.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

LIMIT_S = 180
PAD_MS = 1000
DEFAULT_VOICE = "Samantha"
SRT_NAME = "rebuttal-demo.srt"
SAY_MISSING = "say not found: narration needs macOS say"
FFPROBE_MISSING = "ffprobe not found: brew install ffmpeg"
FFMPEG_MISSING = "ffmpeg not found: brew install ffmpeg"


def hold_ms(min_seconds: float, narration_ms: int) -> int:
    return max(round(min_seconds * 1000), narration_ms + PAD_MS)


def srt_time(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _by_id(timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in timeline}


def build_srt(shots: list[dict[str, Any]], timeline: list[dict[str, Any]]) -> str:
    by_id = _by_id(timeline)
    t0 = timeline[0]["startMs"]
    cues = []
    for n, shot in enumerate(shots, start=1):
        entry = by_id[shot["id"]]
        start, end = srt_time(entry["startMs"] - t0), srt_time(entry["endMs"] - t0)
        cues.append(f"{n}\n{start} --> {end}\n{shot['narration']}\n")
    return "\n".join(cues)


def check_length(seconds: float) -> None:
    if seconds >= LIMIT_S:
        raise ValueError(f"video is {seconds:.1f} s, but it must be under the {LIMIT_S} s limit")


def build_ffmpeg_cmd(
    work: Path, out: Path, shots: list[dict[str, Any]], timeline: list[dict[str, Any]]
) -> list[str]:
    by_id = _by_id(timeline)
    t0 = timeline[0]["startMs"]
    n = len(shots)
    audio_inputs: list[str] = []
    graph: list[str] = []
    for k, shot in enumerate(shots, start=1):
        audio_inputs += ["-i", str(work / "audio" / f"{shot['id']}.aiff")]
        graph.append(f"[{k}:a]adelay={by_id[shot['id']]['startMs'] - t0}:all=1[a{k}]")
    labels = "".join(f"[a{k}]" for k in range(1, n + 1))
    graph.append(f"{labels}amix=inputs={n}:normalize=0:duration=longest[aout]")
    duration = (timeline[-1]["endMs"] - t0) / 1000
    return [
        "ffmpeg", "-y", "-ss", f"{t0 / 1000:.3f}", "-i", str(work / "screen.webm"),
        *audio_inputs, "-i", str(work / SRT_NAME),
        "-filter_complex", ";".join(graph),
        "-map", "0:v", "-map", "[aout]", "-map", f"{n + 1}:s",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text",
        "-t", f"{duration:.3f}", str(out),
    ]


def _run(argv: list[str], missing: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, **kwargs)
    except FileNotFoundError:
        raise SystemExit(missing) from None


def _load_shots(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["shots"]


def _listed_voices(listing: str) -> set[str]:
    """Voice names from `say -v ?` lines such as 'Samantha (English (US)) en_US    # Hello!'."""
    names: set[str] = set()
    for line in listing.splitlines():
        fields = line.split("#", 1)[0].rsplit(None, 1)
        if fields:
            names.add(fields[0])
    return names


def _check_voice(voice: str) -> None:
    listing = _run(["say", "-v", "?"], SAY_MISSING, capture_output=True, text=True).stdout
    names = _listed_voices(listing)
    # Exact name, or the base name before " (", so 'Samantha' matches 'Samantha (English (US))'. Never a prefix.
    if not voice or not any(voice in (name, name.split(" (", 1)[0]) for name in names):
        raise SystemExit(
            f"voice {voice!r} is not installed. List the voices with `say -v ?` and set VIDEO_VOICE to one of them."
        )


def narrate(shots_path: Path, work: Path, voice: str) -> None:
    shots = _load_shots(shots_path)
    audio = work / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    _check_voice(voice)
    durations: dict[str, dict[str, int]] = {}
    for shot in shots:
        aiff = audio / f"{shot['id']}.aiff"
        _run(["say", "-v", voice, "-o", str(aiff), "--", shot["narration"]], SAY_MISSING, check=True)
        probe = _run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(aiff)],
            FFPROBE_MISSING,
            capture_output=True,
            text=True,
            check=True,
        )
        narration_ms = round(float(probe.stdout) * 1000)
        durations[shot["id"]] = {
            "narrationMs": narration_ms,
            "holdMs": hold_ms(shot["minSeconds"], narration_ms),
        }
    (work / "durations.json").write_text(json.dumps(durations, indent=2) + "\n", encoding="utf-8")


def assemble(shots_path: Path, work: Path, out: Path) -> float:
    shots = _load_shots(shots_path)
    timeline = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
    if [entry["id"] for entry in timeline] != [shot["id"] for shot in shots]:
        raise ValueError("timeline.json ids differ from the shots file (same ids, same order required)")
    seconds = (timeline[-1]["endMs"] - timeline[0]["startMs"]) / 1000
    check_length(seconds)
    (work / SRT_NAME).write_text(build_srt(shots, timeline), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(build_ffmpeg_cmd(work, out, shots, timeline), FFMPEG_MISSING, check=True)
    return seconds


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Narrate the demo shots and assemble the final video.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    narrate_ap = sub.add_parser("narrate", help="write narration audio and durations.json")
    narrate_ap.add_argument("--shots", type=Path, required=True)
    narrate_ap.add_argument("--work", type=Path, required=True)
    narrate_ap.add_argument("--voice", default=os.environ.get("VIDEO_VOICE") or DEFAULT_VOICE)
    assemble_ap = sub.add_parser("assemble", help="write the SRT and mux the final video")
    assemble_ap.add_argument("--shots", type=Path, required=True)
    assemble_ap.add_argument("--work", type=Path, required=True)
    assemble_ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "narrate":
        narrate(args.shots, args.work, args.voice)
    else:
        seconds = assemble(args.shots, args.work, args.out)
        print(f"Wrote {args.out} ({seconds:.3f} s)")


if __name__ == "__main__":
    main()
