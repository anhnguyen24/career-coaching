"""
scorer.py — Survey scoring engine

Reads a survey JSON file and scores a set of answers.
Supports MBTI (average), Holland (sum), OCEAN (average with reverse),
and any composite scores defined in the JSON.

Usage:
    from scorer import Scorer
    scorer = Scorer.from_file("survey_v2.json")
    results = scorer.score(answers)
    # answers = {1: 3, 2: 4, 3: 4, ...} (question number → score 1-5)
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# Data classes
# ============================================================

@dataclass
class GroupScore:
    id: str
    name: str
    score: float        # avg or sum depending on method
    raw_scores: list[int]


@dataclass
class MBTIAxisResult:
    axis: str           # e.g. "EI"
    group_a: GroupScore
    group_b: GroupScore
    winner: str         # e.g. "E"
    gap: float


@dataclass
class MBTIResult:
    axes: list[MBTIAxisResult]
    type: str           # e.g. "ENTP"
    gap_avg: float
    clarity: str        # e.g. "Khá rõ"
    note: str


@dataclass
class HollandResult:
    groups: list[GroupScore]
    top3: list[str]     # e.g. ["S", "A", "C"]
    top3_label: str     # e.g. "SAC"


@dataclass
class OceanResult:
    groups: list[GroupScore]


@dataclass
class CompositeComponentResult:
    source: str
    weight: float
    raw_value: float
    weighted_value: float


@dataclass
class CompositeScoreResult:
    id: str
    name: str
    label: str
    components: list[CompositeComponentResult]
    score: float
    interpretation: str


@dataclass
class SurveyResult:
    version: str
    mbti: MBTIResult | None = None
    holland: HollandResult | None = None
    ocean: OceanResult | None = None
    composite_scores: list[CompositeScoreResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert result to a plain dict for serialisation."""
        out: dict[str, Any] = {"version": self.version}
        if self.mbti:
            out["mbti"] = {
                "type":     self.mbti.type,
                "gap_avg":  round(self.mbti.gap_avg, 4),
                "clarity":  self.mbti.clarity,
                "note":     self.mbti.note,
                "axes": [
                    {
                        "axis":      ax.axis,
                        "group_a":   {"id": ax.group_a.id, "score": round(ax.group_a.score, 4)},
                        "group_b":   {"id": ax.group_b.id, "score": round(ax.group_b.score, 4)},
                        "winner":    ax.winner,
                        "gap":       round(ax.gap, 4),
                    }
                    for ax in self.mbti.axes
                ],
            }
        if self.holland:
            out["holland"] = {
                "top3":       self.holland.top3,
                "top3_label": self.holland.top3_label,
                "groups": [
                    {"id": g.id, "name": g.name, "score": g.score}
                    for g in self.holland.groups
                ],
            }
        if self.ocean:
            out["ocean"] = {
                "groups": [
                    {"id": g.id, "name": g.name, "score": round(g.score, 4)}
                    for g in self.ocean.groups
                ]
            }
        if self.composite_scores:
            out["composite_scores"] = [
                {
                    "id":             cs.id,
                    "name":           cs.name,
                    "label":          cs.label,
                    "score":          round(cs.score, 4),
                    "interpretation": cs.interpretation,
                    "components": [
                        {
                            "source":           c.source,
                            "weight":           c.weight,
                            "raw_value":        round(c.raw_value, 4),
                            "weighted_value":   round(c.weighted_value, 4),
                        }
                        for c in cs.components
                    ],
                }
                for cs in self.composite_scores
            ]
        return out


# ============================================================
# Scorer
# ============================================================

class Scorer:
    """
    Loads a survey JSON and scores a dict of answers.

    answers: {question_number: score} where score is 1–scale_max
    """

    def __init__(self, survey: dict):
        self._survey = survey
        self._scale_max: int = survey["metadata"]["scale"]["max"]
        # Build lookup: question_number → question definition
        self._questions: dict[int, dict] = {}
        for test in survey["tests"]:
            for q in test["questions"]:
                self._questions[q["number"]] = q
        # Build lookup: test_id → scoring config
        self._test_scoring: dict[str, dict] = {
            ts["test_id"]: ts for ts in survey["scoring"]["tests"]
        }

    @classmethod
    def from_file(cls, path: str | Path) -> "Scorer":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_json(cls, json_str: str) -> "Scorer":
        return cls(json.loads(json_str))

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def score(self, answers: dict[int, int]) -> SurveyResult:
        result = SurveyResult(version=self._survey["version"])

        for test in self._survey["tests"]:
            tid = test["id"]
            ts  = self._test_scoring.get(tid)
            if ts is None:
                continue
            method = ts["method"]

            if method == "average":
                result.mbti = self._score_mbti(ts, answers)
            elif method == "sum":
                result.holland = self._score_holland(ts, answers)
            elif method == "average_with_reverse":
                result.ocean = self._score_ocean(ts, answers)

        for cs_def in self._survey["scoring"].get("composite_scores", []):
            result.composite_scores.append(
                self._score_composite(cs_def, result, answers)
            )

        return result

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    def _apply_score(self, question_number: int, raw: int) -> int:
        """Apply reverse scoring if needed."""
        q = self._questions.get(question_number)
        if q and q.get("reversed"):
            return (self._scale_max + 1) - raw
        return raw

    def _avg(self, numbers: list[int], answers: dict[int, int], reverse_numbers: list[int] | None = None) -> float:
        """Average of forward questions plus any reversed questions."""
        scores: list[float] = []
        for n in numbers:
            if n in answers:
                scores.append(answers[n])
        for n in (reverse_numbers or []):
            if n in answers:
                scores.append((self._scale_max + 1) - answers[n])
        return sum(scores) / len(scores) if scores else 0.0

    def _sum(self, numbers: list[int], answers: dict[int, int]) -> float:
        return float(sum(answers[n] for n in numbers if n in answers))

    def _interpret(self, score: float, thresholds: list[dict]) -> str:
        for t in thresholds:
            if t["max"] is None or score < t["max"]:
                return t["label"]
        return thresholds[-1]["label"]

    # ----------------------------------------------------------
    # MBTI
    # ----------------------------------------------------------

    def _score_mbti(self, ts: dict, answers: dict[int, int]) -> MBTIResult:
        groups_by_id: dict[str, GroupScore] = {}
        for g in ts["groups"]:
            avg = self._avg(g["forward"], answers, g.get("reversed"))
            groups_by_id[g["id"]] = GroupScore(
                id=g["id"],
                name=g["name"],
                score=round(avg, 4),
                raw_scores=[answers.get(n, 0) for n in g["forward"] + g.get("reversed", [])],
            )

        # Build axes from paired_with relationships
        seen_pairs: set[frozenset] = set()
        axes: list[MBTIAxisResult] = []
        mbti_type_letters: list[str] = []

        for g in ts["groups"]:
            gid    = g["id"]
            paired = g.get("paired_with")
            if not paired:
                continue
            pair_key = frozenset([gid, paired])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            ga = groups_by_id[gid]
            gb = groups_by_id[paired]
            winner = gid if ga.score >= gb.score else paired
            gap    = abs(ga.score - gb.score)
            clarity = self._interpret(gap, ts.get("clarity_thresholds", []))

            axes.append(MBTIAxisResult(
                axis=f"{gid}/{paired}",
                group_a=ga,
                group_b=gb,
                winner=winner,
                gap=round(gap, 4),
            ))
            mbti_type_letters.append(winner)

        gap_avg  = round(sum(ax.gap for ax in axes) / len(axes), 4) if axes else 0.0
        clarity  = self._interpret(gap_avg, ts.get("overall_clarity_thresholds", []))
        weak_axes = sum(1 for ax in axes if ax.gap < 0.40)
        note = (
            "Có từ 2 trục nghiêng nhẹ trở xuống — nên dùng MBTI như lớp tham khảo mềm."
            if weak_axes >= 2
            else "MBTI có độ rõ tương đối tốt, nhưng vẫn nên đọc cùng Holland và OCEAN."
        )

        return MBTIResult(
            axes=axes,
            type="".join(mbti_type_letters),
            gap_avg=gap_avg,
            clarity=clarity,
            note=note,
        )

    # ----------------------------------------------------------
    # Holland
    # ----------------------------------------------------------

    def _score_holland(self, ts: dict, answers: dict[int, int]) -> HollandResult:
        groups: list[GroupScore] = []
        for g in ts["groups"]:
            total = self._sum(g["forward"], answers)
            groups.append(GroupScore(
                id=g["id"],
                name=g["name"],
                score=total,
                raw_scores=[answers.get(n, 0) for n in g["forward"]],
            ))

        sorted_groups = sorted(groups, key=lambda x: x.score, reverse=True)
        top3 = [g.id for g in sorted_groups[:3]]

        return HollandResult(
            groups=groups,
            top3=top3,
            top3_label="".join(top3),
        )

    # ----------------------------------------------------------
    # OCEAN
    # ----------------------------------------------------------

    def _score_ocean(self, ts: dict, answers: dict[int, int]) -> OceanResult:
        groups: list[GroupScore] = []
        for g in ts["groups"]:
            avg = self._avg(g["forward"], answers, g.get("reversed"))
            groups.append(GroupScore(
                id=g["id"],
                name=g["name"],
                score=round(avg, 4),
                raw_scores=[answers.get(n, 0) for n in g["forward"] + g.get("reversed", [])],
            ))
        return OceanResult(groups=groups)

    # ----------------------------------------------------------
    # Composite scores
    # ----------------------------------------------------------

    def _score_composite(
        self,
        cs_def: dict,
        result: SurveyResult,
        answers: dict[int, int],
    ) -> CompositeScoreResult:
        components: list[CompositeComponentResult] = []
        total = 0.0

        for comp in cs_def["components"]:
            source = comp["source"]
            weight = comp["weight"]

            if source == "bipolar_ratio":
                raw = self._compute_bipolar_ratio(comp, result)
            elif source == "test_group":
                raw = self._lookup_group_score(comp["test_id"], comp["group_id"], result)
            elif source == "question_subset":
                raw = self._avg(comp.get("forward", []), answers, comp.get("reversed", []))
            else:
                raise ValueError(f"Unknown composite source: {source!r}")

            weighted = weight * raw
            total   += weighted
            components.append(CompositeComponentResult(
                source=source,
                weight=weight,
                raw_value=raw,
                weighted_value=weighted,
            ))

        interpretation = self._interpret(total, cs_def.get("interpretation_thresholds", []))
        return CompositeScoreResult(
            id=cs_def["id"],
            name=cs_def["name"],
            label=cs_def.get("label", cs_def["id"].upper()),
            components=components,
            score=round(total, 4),
            interpretation=interpretation,
        )

    def _compute_bipolar_ratio(self, comp: dict, result: SurveyResult) -> float:
        """Compute bipolar ratio score e.g. 1 + 4 * (E / (E + I))."""
        formula = comp["ratio_formula"]
        numer_id = formula["numerator_group"]
        denom_ids = formula["denominator_groups"]
        scale_min = formula.get("scale_min", 1)
        scale_max = formula.get("scale_max", 5)

        test_id = comp["test_id"]
        groups = self._get_test_groups(test_id, result)

        numer  = groups[numer_id]
        denom  = sum(groups[d] for d in denom_ids)

        if denom == 0:
            ratio = 0.5
        else:
            ratio = numer / denom

        return scale_min + (scale_max - scale_min) * ratio

    def _lookup_group_score(self, test_id: str, group_id: str, result: SurveyResult) -> float:
        groups = self._get_test_groups(test_id, result)
        return groups.get(group_id, 0.0)

    def _get_test_groups(self, test_id: str, result: SurveyResult) -> dict[str, float]:
        """Return {group_id: score} for a given test result."""
        if test_id == "mbti" and result.mbti:
            groups = {}
            for ax in result.mbti.axes:
                groups[ax.group_a.id] = ax.group_a.score
                groups[ax.group_b.id] = ax.group_b.score
            return groups
        if test_id == "holland" and result.holland:
            return {g.id: g.score for g in result.holland.groups}
        if test_id == "ocean" and result.ocean:
            return {g.id: g.score for g in result.ocean.groups}
        return {}
