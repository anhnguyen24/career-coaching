"""
tests/test_scorer.py

Unit tests for the survey scorer.
Uses HN-2026-0007 (Vũ Thị Giáng Hương) as the primary test case —
we have manually verified all scores for this submission.

Run:
    python -m pytest tests/test_scorer.py -v
    python -m pytest tests/test_scorer.py -v --tb=short
"""

import json
import math
import sys
from pathlib import Path

import pytest

# Allow running from repo root or src/
sys.path.insert(0, str(Path(__file__).parent.parent))
from scorer import Scorer

# ============================================================
# Fixtures
# ============================================================

SURVEY_FILE = Path(__file__).parent.parent / "src" / "survey_versions" / "survey_v2.json"


@pytest.fixture(scope="module")
def scorer() -> Scorer:
    return Scorer.from_file(SURVEY_FILE)


# HN-2026-0007 — Vũ Thị Giáng Hương — all 180 answers
HN_2026_0007_ANSWERS = {
    # MBTI — Test 1
    1: 3, 2: 4, 3: 4, 4: 2, 5: 5, 6: 3,   # E
    7: 1, 8: 1, 9: 1, 10: 3, 11: 1, 12: 3, # I
    13: 2, 14: 1, 15: 2, 16: 1, 17: 1, 18: 1, 19: 1, 20: 1, 21: 2, 22: 2, 23: 1, 24: 1,  # S
    25: 3, 26: 2, 27: 2, 28: 2, 29: 1, 30: 1, 31: 2, 32: 1, 33: 1, 34: 1, 35: 1, 36: 1,  # N
    37: 3, 38: 2, 39: 1, 40: 1, 41: 3, 42: 3,  # T
    43: 1, 44: 1, 45: 1, 46: 2, 47: 1, 48: 1,  # F
    49: 3, 50: 1, 51: 1, 52: 1, 53: 2, 54: 1,  # J
    55: 3, 56: 1, 57: 2, 58: 1, 59: 3, 60: 2,  # P
    # Holland — Test 2
    61: 5, 62: 1, 63: 3, 64: 1, 65: 1, 66: 2, 67: 4, 68: 2, 69: 3, 70: 3,   # R
    71: 1, 72: 4, 73: 5, 74: 4, 75: 5, 76: 1, 77: 4, 78: 1, 79: 4, 80: 5,   # I
    81: 5, 82: 5, 83: 2, 84: 4, 85: 5, 86: 3, 87: 5, 88: 2, 89: 3, 90: 5,   # A
    91: 2, 92: 5, 93: 5, 94: 5, 95: 5, 96: 1, 97: 5, 98: 5, 99: 3, 100: 5,  # S
    101: 2, 102: 4, 103: 4, 104: 3, 105: 4, 106: 2, 107: 3, 108: 3, 109: 5, 110: 2,  # E
    111: 2, 112: 5, 113: 3, 114: 5, 115: 5, 116: 5, 117: 5, 118: 2, 119: 4, 120: 2,  # C
    # OCEAN — Test 3
    121: 2, 122: 5, 123: 4, 124: 5, 125: 4, 126: 5, 127: 5, 128: 3, 129: 4, 130: 5, 131: 2, 132: 1,  # O
    133: 4, 134: 5, 135: 3, 136: 4, 137: 5, 138: 5, 139: 5, 140: 5, 141: 3, 142: 1, 143: 1, 144: 3,  # C
    145: 4, 146: 3, 147: 3, 148: 3, 149: 2, 150: 3, 151: 3, 152: 2, 153: 4, 154: 1, 155: 4, 156: 3,  # E
    157: 5, 158: 5, 159: 5, 160: 5, 161: 5, 162: 3, 163: 5, 164: 5, 165: 2, 166: 3, 167: 1, 168: 2,  # A
    169: 4, 170: 4, 171: 5, 172: 4, 173: 2, 174: 4, 175: 3, 176: 1, 177: 4, 178: 2, 179: 2, 180: 3,  # N
}


@pytest.fixture(scope="module")
def result(scorer):
    return scorer.score(HN_2026_0007_ANSWERS)


# ============================================================
# Helper
# ============================================================

def approx(value: float, expected: float, tol: float = 0.01) -> bool:
    return abs(value - expected) <= tol


# ============================================================
# TEST 1 — MBTI
# ============================================================

class TestMBTI:

    def test_mbti_result_exists(self, result):
        assert result.mbti is not None

    def test_mbti_type(self, result):
        assert result.mbti.type == "ENTP", (
            f"Expected ENTP, got {result.mbti.type}"
        )

    def test_e_avg(self, result):
        # E: (3+4+4+2+5+3)/6 = 21/6 = 3.5
        e_axis = next(ax for ax in result.mbti.axes if "E" in ax.axis)
        e_score = e_axis.group_a.score if e_axis.group_a.id == "E" else e_axis.group_b.score
        assert approx(e_score, 3.5), f"Expected E avg 3.5, got {e_score}"

    def test_i_avg(self, result):
        # I: (1+1+1+3+1+3)/6 = 10/6 = 1.6667
        e_axis = next(ax for ax in result.mbti.axes if "E" in ax.axis)
        i_score = e_axis.group_b.score if e_axis.group_b.id == "I" else e_axis.group_a.score
        assert approx(i_score, 1.6667), f"Expected I avg 1.6667, got {i_score}"

    def test_s_avg(self, result):
        # S: (2+1+2+1+1+1+1+1+2+2+1+1)/12 = 16/12 = 1.3333
        sn_axis = next(ax for ax in result.mbti.axes if "S" in ax.axis)
        s_score = sn_axis.group_a.score if sn_axis.group_a.id == "S" else sn_axis.group_b.score
        assert approx(s_score, 1.3333), f"Expected S avg 1.3333, got {s_score}"

    def test_n_avg(self, result):
        # N: (3+2+2+2+1+1+2+1+1+1+1+1)/12 = 18/12 = 1.5
        sn_axis = next(ax for ax in result.mbti.axes if "S" in ax.axis)
        n_score = sn_axis.group_b.score if sn_axis.group_b.id == "N" else sn_axis.group_a.score
        assert approx(n_score, 1.5), f"Expected N avg 1.5, got {n_score}"

    def test_t_avg(self, result):
        # T: (3+2+1+1+3+3)/6 = 13/6 = 2.1667
        tf_axis = next(ax for ax in result.mbti.axes if "T" in ax.axis)
        t_score = tf_axis.group_a.score if tf_axis.group_a.id == "T" else tf_axis.group_b.score
        assert approx(t_score, 2.1667), f"Expected T avg 2.1667, got {t_score}"

    def test_f_avg(self, result):
        # F: (1+1+1+2+1+1)/6 = 7/6 = 1.1667
        tf_axis = next(ax for ax in result.mbti.axes if "T" in ax.axis)
        f_score = tf_axis.group_b.score if tf_axis.group_b.id == "F" else tf_axis.group_a.score
        assert approx(f_score, 1.1667), f"Expected F avg 1.1667, got {f_score}"

    def test_j_avg(self, result):
        # J: (3+1+1+1+2+1)/6 = 9/6 = 1.5
        jp_axis = next(ax for ax in result.mbti.axes if "J" in ax.axis)
        j_score = jp_axis.group_a.score if jp_axis.group_a.id == "J" else jp_axis.group_b.score
        assert approx(j_score, 1.5), f"Expected J avg 1.5, got {j_score}"

    def test_p_avg(self, result):
        # P: (3+1+2+1+3+2)/6 = 12/6 = 2.0
        jp_axis = next(ax for ax in result.mbti.axes if "J" in ax.axis)
        p_score = jp_axis.group_b.score if jp_axis.group_b.id == "P" else jp_axis.group_a.score
        assert approx(p_score, 2.0), f"Expected P avg 2.0, got {p_score}"

    def test_ei_gap(self, result):
        # EI gap: |3.5 - 1.6667| = 1.8333
        ei_axis = next(ax for ax in result.mbti.axes if "E" in ax.axis)
        assert approx(ei_axis.gap, 1.8333), f"Expected EI gap 1.8333, got {ei_axis.gap}"

    def test_sn_gap(self, result):
        # SN gap: |1.3333 - 1.5| = 0.1667
        sn_axis = next(ax for ax in result.mbti.axes if "S" in ax.axis)
        assert approx(sn_axis.gap, 0.1667), f"Expected SN gap 0.1667, got {sn_axis.gap}"

    def test_tf_gap(self, result):
        # TF gap: |2.1667 - 1.1667| = 1.0
        tf_axis = next(ax for ax in result.mbti.axes if "T" in ax.axis)
        assert approx(tf_axis.gap, 1.0), f"Expected TF gap 1.0, got {tf_axis.gap}"

    def test_jp_gap(self, result):
        # JP gap: |1.5 - 2.0| = 0.5
        jp_axis = next(ax for ax in result.mbti.axes if "J" in ax.axis)
        assert approx(jp_axis.gap, 0.5), f"Expected JP gap 0.5, got {jp_axis.gap}"

    def test_gap_avg(self, result):
        # gap avg: (1.8333 + 0.1667 + 1.0 + 0.5) / 4 = 3.5 / 4 = 0.875
        assert approx(result.mbti.gap_avg, 0.875), (
            f"Expected gap avg 0.875, got {result.mbti.gap_avg}"
        )

    def test_clarity(self, result):
        assert result.mbti.clarity == "Khá rõ", (
            f"Expected 'Khá rõ', got {result.mbti.clarity!r}"
        )


# ============================================================
# TEST 2 — Holland
# ============================================================

class TestHolland:

    def test_holland_result_exists(self, result):
        assert result.holland is not None

    def test_r_total(self, result):
        # R: 5+1+3+1+1+2+4+2+3+3 = 25
        r = next(g for g in result.holland.groups if g.id == "R")
        assert r.score == 25, f"Expected R=25, got {r.score}"

    def test_i_total(self, result):
        # I: 1+4+5+4+5+1+4+1+4+5 = 34
        i = next(g for g in result.holland.groups if g.id == "I")
        assert i.score == 34, f"Expected I=34, got {i.score}"

    def test_a_total(self, result):
        # A: 5+5+2+4+5+3+5+2+3+5 = 39
        a = next(g for g in result.holland.groups if g.id == "A")
        assert a.score == 39, f"Expected A=39, got {a.score}"

    def test_s_total(self, result):
        # S: 2+5+5+5+5+1+5+5+3+5 = 41
        s = next(g for g in result.holland.groups if g.id == "S")
        assert s.score == 41, f"Expected S=41, got {s.score}"

    def test_e_total(self, result):
        # E: 2+4+4+3+4+2+3+3+5+2 = 32
        e = next(g for g in result.holland.groups if g.id == "E")
        assert e.score == 32, f"Expected E=32, got {e.score}"

    def test_c_total(self, result):
        # C: 2+5+3+5+5+5+5+2+4+2 = 38
        c = next(g for g in result.holland.groups if g.id == "C")
        assert c.score == 38, f"Expected C=38, got {c.score}"

    def test_top3(self, result):
        assert result.holland.top3 == ["S", "A", "C"], (
            f"Expected top3 ['S','A','C'], got {result.holland.top3}"
        )

    def test_top3_label(self, result):
        assert result.holland.top3_label == "SAC"


# ============================================================
# TEST 3 — OCEAN
# ============================================================

class TestOCEAN:

    def test_ocean_result_exists(self, result):
        assert result.ocean is not None

    def test_o_avg(self, result):
        # O forward: 2,5,4,5,4,5,5,3,4,5 = 42; reversed: 131→6-2=4, 132→6-1=5
        # total = 42+4+5 = 51; avg = 51/12 = 4.25
        o = next(g for g in result.ocean.groups if g.id == "O")
        assert approx(o.score, 4.25), f"Expected O=4.25, got {o.score}"

    def test_c_avg(self, result):
        # C forward: 4,5,3,4,5,5,5,5 = 36; reversed: 141→3, 142→5, 143→5, 144→3
        # total = 36+3+5+5+3 = 52; avg = 52/12 = 4.3333
        c = next(g for g in result.ocean.groups if g.id == "C")
        assert approx(c.score, 4.3333), f"Expected C=4.3333, got {c.score}"

    def test_e_avg(self, result):
        # E forward: 4,3,3,3,2,3,3,2 = 23; reversed: 153→2, 154→5, 155→2, 156→3
        # total = 23+2+5+2+3 = 35; avg = 35/12 = 2.9167
        e = next(g for g in result.ocean.groups if g.id == "E")
        assert approx(e.score, 2.9167), f"Expected E=2.9167, got {e.score}"

    def test_a_avg(self, result):
        # A forward: 5,5,5,5,5,3,5,5 = 38; reversed: 165→4, 166→3, 167→5, 168→4
        # total = 38+4+3+5+4 = 54; avg = 54/12 = 4.5
        a = next(g for g in result.ocean.groups if g.id == "A")
        assert approx(a.score, 4.5), f"Expected A=4.5, got {a.score}"

    def test_n_avg(self, result):
        # N forward: 4,4,5,4,2,4,3,1 = 27; reversed: 177→2, 178→4, 179→4, 180→3
        # total = 27+2+4+4+3 = 40; avg = 40/12 = 3.3333
        n = next(g for g in result.ocean.groups if g.id == "N")
        assert approx(n.score, 3.3333), f"Expected N=3.3333, got {n.score}"


# ============================================================
# SSS composite score
# ============================================================

class TestSSS:

    def test_sss_exists(self, result):
        sss = next((cs for cs in result.composite_scores if cs.id == "sss"), None)
        assert sss is not None

    def test_mbti_social_ratio(self, result):
        # ratio = E / (E + I) = 3.5 / (3.5 + 1.6667) = 3.5 / 5.1667 = 0.6774
        # mbti_social_score = 1 + 4 * 0.6774 = 3.7097
        sss = next(cs for cs in result.composite_scores if cs.id == "sss")
        bipolar = next(c for c in sss.components if c.source == "bipolar_ratio")
        assert approx(bipolar.raw_value, 3.7097, tol=0.02), (
            f"Expected MBTI social score ~3.71, got {bipolar.raw_value}"
        )

    def test_ocean_e_component(self, result):
        # OCEAN E avg = 2.9167
        sss = next(cs for cs in result.composite_scores if cs.id == "sss")
        ocean_e = next(c for c in sss.components if c.source == "test_group")
        assert approx(ocean_e.raw_value, 2.9167), (
            f"Expected OCEAN_E_avg 2.9167, got {ocean_e.raw_value}"
        )

    def test_raw_social_score(self, result):
        # forward: Q145=4, Q148=3, Q149=2, Q150=3, Q152=2 → sum=14
        # reversed: Q154=1→5, Q155=4→2, Q156=3→3 → sum=10
        # avg of [4,3,2,3,2,5,2,3] = 24/8 = 3.0
        sss = next(cs for cs in result.composite_scores if cs.id == "sss")
        subset = next(c for c in sss.components if c.source == "question_subset")
        assert approx(subset.raw_value, 3.0), (
            f"Expected raw social score 3.0, got {subset.raw_value}"
        )

    def test_sss_total(self, result):
        # SSS = 0.30 * 3.7097 + 0.40 * 2.9167 + 0.30 * 3.0
        #      = 1.1129 + 1.1667 + 0.9 = 3.1796 ≈ 3.18
        sss = next(cs for cs in result.composite_scores if cs.id == "sss")
        assert approx(sss.score, 3.18, tol=0.05), (
            f"Expected SSS ~3.18, got {sss.score}"
        )

    def test_sss_interpretation(self, result):
        sss = next(cs for cs in result.composite_scores if cs.id == "sss")
        assert sss.interpretation == "Trung bình", (
            f"Expected 'Trung bình', got {sss.interpretation!r}"
        )


# ============================================================
# Edge cases
# ============================================================

class TestEdgeCases:

    def test_missing_answers_returns_zeros(self, scorer):
        """If answers are missing, score should not crash."""
        result = scorer.score({})
        assert result.mbti is not None
        assert result.holland is not None
        assert result.ocean is not None

    def test_all_ones(self, scorer):
        """All 1s should produce low scores."""
        answers = {i: 1 for i in range(1, 181)}
        result = scorer.score(answers)
        # OCEAN reversed questions get 6-1=5, so not all low — but Holland R should be low
        r = next(g for g in result.holland.groups if g.id == "R")
        assert r.score == 10, f"All 1s → R sum should be 10, got {r.score}"

    def test_all_fives(self, scorer):
        """All 5s should produce high Holland scores."""
        answers = {i: 5 for i in range(1, 181)}
        result = scorer.score(answers)
        r = next(g for g in result.holland.groups if g.id == "R")
        assert r.score == 50, f"All 5s → R sum should be 50, got {r.score}"

    def test_result_to_dict(self, result):
        """to_dict() should be serialisable."""
        d = result.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 100

    def test_version_in_result(self, result):
        assert result.version == "v2"


# ============================================================
# Schema integrity tests (run on the JSON file directly)
# ============================================================

class TestSchemaIntegrity:

    def test_total_questions(self):
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        total = sum(len(t["questions"]) for t in data["tests"])
        assert total == data["metadata"]["total_questions"], (
            f"total_questions mismatch: metadata says {data['metadata']['total_questions']}, "
            f"actual {total}"
        )

    def test_question_numbers_sequential(self):
        """Question numbers must be 1-180 with no gaps or duplicates."""
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        numbers = sorted(q["number"] for t in data["tests"] for q in t["questions"])
        expected = list(range(1, data["metadata"]["total_questions"] + 1))
        assert numbers == expected, (
            f"Question numbers are not sequential 1-{data['metadata']['total_questions']}"
        )

    def test_axis_matches_scoring(self):
        """Every question axis must appear in the scoring groups for that test."""
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        scoring_groups = {
            ts["test_id"]: {g["id"] for g in ts["groups"]}
            for ts in data["scoring"]["tests"]
        }
        for test in data["tests"]:
            tid = test["id"]
            valid_axes = scoring_groups.get(tid, set())
            for q in test["questions"]:
                assert q["axis"] in valid_axes, (
                    f"Test {tid!r}: question {q['number']} has axis {q['axis']!r} "
                    f"not in scoring groups {valid_axes}"
                )

    def test_reversed_questions_match_axis(self):
        """Reversed questions in scoring groups must have reversed=True in the question list."""
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        questions_by_number = {
            q["number"]: q
            for t in data["tests"]
            for q in t["questions"]
        }
        for ts in data["scoring"]["tests"]:
            for g in ts["groups"]:
                for n in g.get("reversed", []):
                    q = questions_by_number.get(n)
                    assert q is not None, f"Reversed question {n} not found in questions"
                    assert q["reversed"] is True, (
                        f"Question {n} is in reversed scoring list "
                        f"but has reversed=false in question definition"
                    )

    def test_composite_weights_sum_to_one(self):
        """Component weights in each composite score must sum to 1.0."""
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for cs in data["scoring"].get("composite_scores", []):
            total = sum(c["weight"] for c in cs["components"])
            assert abs(total - 1.0) < 0.001, (
                f"Composite score {cs['id']!r} weights sum to {total}, expected 1.0"
            )

    def test_interpretation_thresholds_ordered(self):
        """Thresholds must be ordered low → high, with last max = null."""
        with open(SURVEY_FILE, encoding="utf-8") as f:
            data = json.load(f)

        def check_thresholds(thresholds: list, label: str):
            for i, t in enumerate(thresholds[:-1]):
                assert t["max"] is not None, f"{label}: non-last threshold has null max"
            assert thresholds[-1]["max"] is None, f"{label}: last threshold must have null max"

        for ts in data["scoring"]["tests"]:
            for key in ["clarity_thresholds", "overall_clarity_thresholds", "interpretation_thresholds"]:
                if key in ts:
                    check_thresholds(ts[key], f"test {ts['test_id']} {key}")
        for cs in data["scoring"].get("composite_scores", []):
            check_thresholds(cs["interpretation_thresholds"], f"composite {cs['id']}")
