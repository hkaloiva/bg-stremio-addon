"""Lightweight subtitle matching helpers centered on probe fingerprints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple

MAX_CUE_DENSITY = 0.5  # cues per second judged as ideal density
MAX_OFFSET_SECONDS = 3.0  # offsets larger than this heavily penalized


@dataclass
class SubtitleCandidate:
    """Minimal candidate metadata surface for matching."""

    provider: str
    url: str
    sha1: str
    runtime: float
    cues: List[Tuple[int, int]]
    lang: str
    score: float = field(default=0.0, compare=False)

    @property
    def start_offset_seconds(self) -> float:
        if not self.cues:
            return 0.0
        return max(0.0, self.cues[0][0] / 1000.0)


class SubtitleMatch:
    """Score subtitle candidates against a decisive probe payload."""

    def __init__(self, probe: dict, candidates: Iterable[SubtitleCandidate]):
        self.probe = probe
        self.candidates = list(candidates)

    def score_sub(self, candidate: SubtitleCandidate) -> float:
        target_sha = self.probe.get("sha1", "")
        hash_score = 1.0 if candidate.sha1 == target_sha and target_sha else 0.0
        runtime_score = self._runtime_ratio(candidate.runtime, float(self.probe.get("runtime") or 0.0))
        cue_density_score = self._cue_density(candidate)
        offset_score = self._offset_score(candidate)
        score = (
            hash_score * 0.6
            + runtime_score * 0.2
            + cue_density_score * 0.1
            + offset_score * 0.1
        )
        return max(0.0, min(score, 1.0))

    def best(self, top_k: int = 3) -> List[SubtitleCandidate]:
        ranked = []
        for candidate in self.candidates:
            candidate.score = self.score_sub(candidate)
            ranked.append(candidate)
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _runtime_ratio(self, candidate_runtime: float, probe_runtime: float) -> float:
        if candidate_runtime <= 0 or probe_runtime <= 0:
            return 0.0
        smaller = min(candidate_runtime, probe_runtime)
        larger = max(candidate_runtime, probe_runtime)
        ratio = smaller / larger
        return max(0.0, min(ratio, 1.0))

    def _cue_density(self, candidate: SubtitleCandidate) -> float:
        if not candidate.cues:
            return 0.0
        probe_runtime = float(self.probe.get("runtime") or 0.0)
        if probe_runtime <= 0:
            return 0.0
        density = len(candidate.cues) / probe_runtime
        return min(density / MAX_CUE_DENSITY, 1.0)

    def _offset_score(self, candidate: SubtitleCandidate) -> float:
        if not candidate.cues:
            return 0.0
        offset = candidate.start_offset_seconds
        if offset <= 0.0:
            return 1.0
        normalized = min(offset / MAX_OFFSET_SECONDS, 1.0)
        return max(0.0, 1.0 - normalized)


__all__ = ["SubtitleMatch", "SubtitleCandidate"]
