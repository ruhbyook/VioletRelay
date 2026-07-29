from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path


_TIMESTAMP = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)
_TAG = re.compile(r"<[^>]+>|\{\\[^}]+\}")


def _time_ms(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    return (
        int(match.group("h")) * 3_600_000
        + int(match.group("m")) * 60_000
        + int(match.group("s")) * 1_000
        + int(match.group("ms"))
    )


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


class SubtitleTrack:
    def __init__(self, cues: list[SubtitleCue]):
        self.cues = sorted(cues, key=lambda cue: cue.start_ms)
        self._starts = [cue.start_ms for cue in self.cues]

    @classmethod
    def from_srt(cls, path: Path) -> "SubtitleTrack":
        raw = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
        cues: list[SubtitleCue] = []
        for block in re.split(r"\n{2,}", raw.strip()):
            lines = [line.rstrip() for line in block.splitlines()]
            if lines and lines[0].strip().isdigit():
                lines.pop(0)
            if not lines or "-->" not in lines[0]:
                continue
            start, end = (part.strip().split()[0] for part in lines.pop(0).split("-->", 1))
            try:
                text = _TAG.sub("", "\n".join(lines).strip())
                cues.append(SubtitleCue(_time_ms(start), _time_ms(end), text))
            except ValueError:
                continue
        return cls(cues)

    def text_at(self, position_ms: int) -> str:
        index = bisect.bisect_right(self._starts, position_ms) - 1
        if index >= 0:
            cue = self.cues[index]
            if cue.start_ms <= position_ms <= cue.end_ms:
                return cue.text
        return ""
