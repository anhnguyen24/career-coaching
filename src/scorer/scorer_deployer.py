"""
scorer/scorer_deployer.py — Generates Scores tab formulas and manages seed rows

What it does:

1. deploy_formulas() — called by --scorer
   - Reads scoring config from survey JSON
   - Injects mock row into Form Responses 2 (permanent)
   - Generates fresh Scores tab formulas from JSON
   - Writes formulas + survey_version tag to a new Scores row (permanent)
   - Waits for recalculation, compares against expected
   - ✅ Pass → both rows stay (new permanent seed row for future submissions)
   - ❌ Fail → deletes both rows, exits with error

2. run_integration_test() — called by --test
   - Same as deploy_formulas() but always deletes both rows after
   - Nothing permanent changes in the sheet

Before running, generate the mock first:
    python tests/generate_mock.py src/survey_versions/survey_v2.json
"""

import json
import os
import sys
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Allow import from parent src/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scorer.scorer import Scorer

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MOCK_FILE = Path(__file__).parent.parent.parent / "tests" / "mock_submission.json"


def _load_mock() -> dict:
    """Load mock submission from file."""
    if not MOCK_FILE.exists():
        print(f"  ❌ Mock file not found: {MOCK_FILE}")
        print(f"  Run first: python tests/generate_mock.py src/survey_versions/survey_vX.json")
        sys.exit(1)
    with open(MOCK_FILE, encoding="utf-8") as f:
        return json.load(f)


def _validate_mock_version(mock: dict, survey: dict):
    """Ensure mock was generated for the same survey version."""
    if mock["version"] != survey["version"]:
        print(
            f"  ❌ Mock version mismatch: mock is {mock['version']!r} "
            f"but survey is {survey['version']!r}"
        )
        print(f"  Run: python tests/generate_mock.py src/survey_versions/survey_{survey['version']}.json")
        sys.exit(1)


# ============================================================
# Column helpers
# ============================================================

# Timestamp + 15 student info fields = 16 columns before Q1
STUDENT_INFO_COLS = 16


def col_letter(n: int) -> str:
    """Convert 1-based column index to A1-style letter (supports AA, AB...)"""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def q_col(question_number: int) -> str:
    """Get the column letter for a given question number in Form Responses 2."""
    col_index = STUDENT_INFO_COLS + question_number
    return col_letter(col_index)


# ============================================================
# ScorerDeployer
# ============================================================

class ScorerDeployer:

    def __init__(self, survey: dict):
        self._survey         = survey
        self._sheet_id       = os.environ["GOOGLE_SHEET_ID"]
        self._scores_sheet   = os.environ.get("SCORES_SHEET_NAME", "Scores")
        self._response_sheet = os.environ.get("RESPONSE_SHEET_NAME", "Form Responses 2")
        self._service        = self._build_service()
        self._scorer         = Scorer(survey)

        self._test_scoring = {
            ts["test_id"]: ts
            for ts in survey["scoring"]["tests"]
        }

    # ----------------------------------------------------------
    # Public: deploy formulas (--scorer) — permanent if passed
    # ----------------------------------------------------------

    def deploy_formulas(self):
        """
        Inject mock row + write Scores formulas permanently.
        Deletes both rows only if comparison fails.
        """
        mock = _load_mock()
        _validate_mock_version(mock, self._survey)

        answers      = {int(k): v for k, v in mock["answers"].items()}
        student_info = mock["student_info"]
        expected     = mock["expected"]
        version      = self._survey["version"]

        print(f"  Mock version: {mock['version']}")
        print(f"  Injecting mock row ({student_info['token']})...")
        data_row = self._inject_test_row(answers, student_info, version)
        print(f"  Mock row inserted at row {data_row} in {self._response_sheet}")

        scores_last_row = self._get_last_row(self._scores_sheet)
        scores_row      = scores_last_row + 1
        formulas        = self._generate_formulas(data_row=data_row, scores_row=scores_row)
        self._write_row(self._scores_sheet, scores_row, formulas)
        self._center_row(self._scores_sheet, scores_row, len(formulas))
        print(f"  Scores formulas written to row {scores_row} (survey_version={version})")

        print(f"  Waiting 5s for Sheets to recalculate...")
        time.sleep(5)

        sheets_scores = self._read_scores_row(scores_row)
        passed        = self._compare(sheets_scores, expected)

        if not passed:
            print(f"\n  ❌ Comparison failed — rolling back...")
            self._delete_row(self._response_sheet, data_row)
            self._delete_row(self._scores_sheet, scores_row)
            print(f"  Both rows deleted")
            sys.exit(1)
        else:
            print(f"\n  ✅ Scores tab seed row deployed and verified")
            print(f"  Mock row (HN-2026-0009) is now the seed row for future submissions")

    # ----------------------------------------------------------
    # Public: integration test (--test) — always temporary
    # ----------------------------------------------------------

    def run_integration_test(self):
        """
        Inject mock row, compare, then always delete both rows.
        Nothing permanent changes in the sheet.
        """
        mock = _load_mock()
        _validate_mock_version(mock, self._survey)

        answers      = {int(k): v for k, v in mock["answers"].items()}
        student_info = mock["student_info"]
        expected     = mock["expected"]
        version      = self._survey["version"]

        print(f"  Mock version: {mock['version']}")
        print(f"  Injecting test row ({student_info['token']})...")
        data_row = self._inject_test_row(answers, student_info, version)
        print(f"  Test row inserted at row {data_row} in {self._response_sheet}")

        scores_last_row = self._get_last_row(self._scores_sheet)
        scores_row      = scores_last_row + 1
        formulas        = self._generate_formulas(data_row=data_row, scores_row=scores_row)
        self._write_row(self._scores_sheet, scores_row, formulas)
        self._center_row(self._scores_sheet, scores_row, len(formulas))
        print(f"  Scores formulas written to row {scores_row}")

        print(f"  Waiting 5s for Sheets to recalculate...")
        time.sleep(5)

        sheets_scores = self._read_scores_row(scores_row)
        passed        = self._compare(sheets_scores, expected)

        print(f"\n  Cleaning up test rows...")
        self._delete_row(self._response_sheet, data_row)
        self._delete_row(self._scores_sheet, scores_row)
        print(f"  Test rows deleted")

        if not passed:
            print(f"\n  ❌ Integration test FAILED — see mismatches above")
            sys.exit(1)
        else:
            print(f"\n  ✅ Integration test PASSED — Scores tab matches expected")

    # ----------------------------------------------------------
    # Formula generation
    # ----------------------------------------------------------

    def _generate_formulas(self, data_row: int, scores_row: int) -> list:
        """
        Generate all Scores tab formulas for a given data row.
        data_row   — row in Form Responses 2 (for question references)
        scores_row — row in Scores tab (for self-references between derived columns)
        """
        rs       = self._response_sheet
        formulas = []

        # A-C: info columns
        formulas.append(f"='{rs}'!A{data_row}")
        formulas.append(f"='{rs}'!B{data_row}")
        formulas.append(f"='{rs}'!C{data_row}")

        # MBTI averages (D-K)
        mbti_ts     = self._test_scoring["mbti"]
        mbti_groups = {g["id"]: g for g in mbti_ts["groups"]}
        axes_order  = [("E","I"), ("S","N"), ("T","F"), ("J","P")]

        for a, b in axes_order:
            for gid in [a, b]:
                g = mbti_groups[gid]
                formulas.append(self._avg_formula(rs, data_row, g["forward"], g.get("reversed", [])))

        # Column map for MBTI groups in Scores tab (D=4 onwards)
        col_map = {gid: col_letter(4 + i) for i, gid in enumerate(["E","I","S","N","T","F","J","P"])}

        e_col = col_map["E"]; i_col = col_map["I"]
        s_col = col_map["S"]; n_col = col_map["N"]
        t_col = col_map["T"]; f_col = col_map["F"]
        j_col = col_map["J"]; p_col = col_map["P"]

        # MBTI type (L)
        formulas.append(
            f'=IF({e_col}{scores_row}>={i_col}{scores_row},"E","I")'
            f'&IF({s_col}{scores_row}>={n_col}{scores_row},"S","N")'
            f'&IF({t_col}{scores_row}>={f_col}{scores_row},"T","F")'
            f'&IF({j_col}{scores_row}>={p_col}{scores_row},"J","P")'
        )

        # Gaps (M-P)
        for a, b in axes_order:
            formulas.append(f"=ROUND(ABS({col_map[a]}{scores_row}-{col_map[b]}{scores_row}),2)")

        # Gap avg (Q)
        gap_start_col = col_letter(13)
        gap_end_col   = col_letter(16)
        formulas.append(f"=ROUND(AVERAGE({gap_start_col}{scores_row}:{gap_end_col}{scores_row}),2)")

        # Clarity (R)
        gap_avg_col = col_letter(17)
        formulas.append(self._clarity_formula(gap_avg_col, scores_row, mbti_ts.get("overall_clarity_thresholds", [])))

        # Note (S)
        formulas.append(
            f'=IF(COUNTIF({col_map["E"]}{scores_row}:{col_map["P"]}{scores_row},"<0.4")>=2,'
            f'"Có từ 2 trục nghiêng nhẹ trở xuống — nên dùng MBTI như lớp tham khảo mềm.",'
            f'"MBTI có độ rõ tương đối tốt, nhưng vẫn nên đọc cùng Holland và OCEAN.")'
        )

        # Holland — SUM per group (T-Y)
        holland_ts        = self._test_scoring["holland"]
        holland_col_start = len(formulas) + 1
        for g in holland_ts["groups"]:
            formulas.append(self._sum_formula(rs, data_row, g["forward"]))

        # Holland Top 3 (Z-AB)
        h_cols = [col_letter(holland_col_start + i) for i in range(len(holland_ts["groups"]))]
        h_ids  = [g["id"] for g in holland_ts["groups"]]
        formulas.append(self._holland_rank_formula(h_cols, h_ids, scores_row, 1))
        formulas.append(self._holland_rank_formula(h_cols, h_ids, scores_row, 2))
        formulas.append(self._holland_rank_formula(h_cols, h_ids, scores_row, 3))

        # Holland Top 3 label (AC)
        top3_col1 = col_letter(len(formulas) - 2)
        top3_col2 = col_letter(len(formulas) - 1)
        top3_col3 = col_letter(len(formulas))
        formulas.append(f"={top3_col1}{scores_row}&\", \"&{top3_col2}{scores_row}&\", \"&{top3_col3}{scores_row}")

        # OCEAN — average with reverse (AD-AH)
        ocean_ts        = self._test_scoring["ocean"]
        ocean_col_start = len(formulas) + 1
        for g in ocean_ts["groups"]:
            formulas.append(self._avg_formula(rs, data_row, g["forward"], g.get("reversed", [])))

        # SSS composite
        sss_def     = next(cs for cs in self._survey["scoring"]["composite_scores"] if cs["id"] == "sss")
        ocean_e_col = col_letter(ocean_col_start + 2)  # O=0, C=1, E=2

        # MBTI social ratio (AI)
        formulas.append(f"=ROUND({e_col}{scores_row}/({e_col}{scores_row}+{i_col}{scores_row}),2)")

        # MBTI social score (AJ)
        ratio_col = col_letter(len(formulas))
        formulas.append(f"=ROUND(1+4*{ratio_col}{scores_row},2)")

        # Raw social score (AK)
        sss_comp = next(c for c in sss_def["components"] if c["source"] == "question_subset")
        formulas.append(self._avg_formula(rs, data_row, sss_comp.get("forward", []), sss_comp.get("reversed", [])))

        # SSS total (AL)
        mbti_ss_col = col_letter(len(formulas) - 1)
        raw_ss_col  = col_letter(len(formulas))
        weights     = {c["source"]: c["weight"] for c in sss_def["components"]}
        w_mbti  = weights.get("bipolar_ratio", 0.30)
        w_ocean = weights.get("test_group", 0.40)
        w_raw   = weights.get("question_subset", 0.30)
        formulas.append(
            f"=ROUND({w_mbti}*{mbti_ss_col}{scores_row}"
            f"+{w_ocean}*{ocean_e_col}{scores_row}"
            f"+{w_raw}*{raw_ss_col}{scores_row},2)"
        )

        # SSS interpretation (AM)
        sss_col = col_letter(len(formulas))
        formulas.append(self._interpret_formula(sss_col, scores_row, sss_def.get("interpretation_thresholds", [])))

        # Survey version (AN) — for historical record
        formulas.append(self._survey['version'])

        return formulas

    def _avg_formula(self, sheet: str, row: int, forward: list, reversed_qs: list) -> str:
        parts  = [f"'{sheet}'!{q_col(n)}{row}" for n in forward]
        parts += [f"6-'{sheet}'!{q_col(n)}{row}" for n in reversed_qs]
        return f"=ROUND(AVERAGE({','.join(parts)}),2)"

    def _sum_formula(self, sheet: str, row: int, questions: list) -> str:
        parts = [f"'{sheet}'!{q_col(n)}{row}" for n in questions]
        return f"=SUM({','.join(parts)})"

    def _holland_rank_formula(self, h_cols: list, h_ids: list, row: int, rank: int) -> str:
        ids_str      = "{" + ",".join(f'"{h}"' for h in h_ids) + "}"
        scores_range = ",".join(f"{c}{row}" for c in h_cols)
        return (
            f"=INDEX({ids_str},MATCH(LARGE({{{scores_range}}},{rank})"
            f",{{{scores_range}}},0))"
        )

    def _clarity_formula(self, col: str, row: int, thresholds: list) -> str:
        if not thresholds:
            return '=""'
        result = f'"{thresholds[-1]["label"]}"'
        for t in reversed(thresholds[:-1]):
            result = f'IF({col}{row}<{t["max"]},"{t["label"]}",{result})'
        return f"={result}"

    def _interpret_formula(self, col: str, row: int, thresholds: list) -> str:
        if not thresholds:
            return '=""'
        result = f'"{thresholds[-1]["label"]}"'
        for t in reversed(thresholds[:-1]):
            result = f'IF({col}{row}<{t["max"]},"{t["label"]}",{result})'
        return f"={result}"

    # ----------------------------------------------------------
    # Shared helpers
    # ----------------------------------------------------------

    def _inject_test_row(self, answers: dict, student_info: dict, version: str) -> int:
        """Append mock test answers to Form Responses 2. Returns new row index."""
        total    = len(answers)
        info_row = [
            "2026-01-01 00:00:00",
            student_info.get("name",           "Integration Test"),
            student_info.get("token",          "HN-2026-0009"),
            student_info.get("dob",            "01/01/2000"),
            student_info.get("gender",         "Khác"),
            student_info.get("grade",          "12"),
            student_info.get("school_year",    "2025-2026"),
            student_info.get("school",         "TEST_SCHOOL"),
            student_info.get("city",           "TEST_CITY"),
            student_info.get("email",          "test@test.internal"),
            student_info.get("phone",          "0000000000"),
            student_info.get("direction",      "TEST"),
            student_info.get("after_school",   "TEST"),
            student_info.get("fav_subjects",   "TEST"),
            student_info.get("fav_activities", "TEST"),
            student_info.get("commitment",     "Đồng ý"),
        ]
        answer_row = [answers[i] for i in range(1, total + 1)]
        row_data   = info_row + answer_row

        result = self._service.spreadsheets().values().append(
            spreadsheetId=self._sheet_id,
            range=f"'{self._response_sheet}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]}
        ).execute()

        updated_range = result["updates"]["updatedRange"]
        row_num = int(updated_range.split("!")[-1].split(":")[0][1:])
        return row_num

    def _read_scores_row(self, row: int) -> list:
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self._sheet_id,
            range=f"'{self._scores_sheet}'!A{row}:AN{row}",
            valueRenderOption="UNFORMATTED_VALUE",
        ).execute()
        values = result.get("values", [[]])
        return values[0] if values else []

    def _compare(self, sheets_scores: list, expected: dict) -> bool:
        """Compare Scores tab output against expected scores from mock_submission.json."""
        passed = True
        tol    = 0.02

        def check(label: str, sheet_val, exp_val):
            nonlocal passed
            try:
                sheet_f = float(sheet_val)
                exp_f   = float(exp_val)
                if abs(sheet_f - exp_f) > tol:
                    print(f"  ❌ {label}: Sheets={sheet_f:.4f}  Expected={exp_f:.4f}")
                    passed = False
                else:
                    print(f"  ✅ {label}: {sheet_f:.4f}")
            except (TypeError, ValueError):
                if str(sheet_val) != str(exp_val):
                    print(f"  ❌ {label}: Sheets={sheet_val!r}  Expected={exp_val!r}")
                    passed = False
                else:
                    print(f"  ✅ {label}: {sheet_val!r}")

        if not sheets_scores:
            print("  ❌ No scores found in Scores tab row")
            return False

        # MBTI
        mbti    = expected.get("mbti", {})
        col_map = {"E": 3, "I": 4, "S": 5, "N": 6, "T": 7, "F": 8, "J": 9, "P": 10}
        for ax in mbti.get("axes", []):
            for pole in ["group_a", "group_b"]:
                gid     = ax[pole]["id"]
                score   = ax[pole]["score"]
                col_idx = col_map.get(gid)
                if col_idx and col_idx < len(sheets_scores):
                    check(f"MBTI_{gid}_avg", sheets_scores[col_idx], score)
        if len(sheets_scores) > 11:
            check("MBTI_type", sheets_scores[11], mbti.get("type", ""))

        # Holland
        holland       = expected.get("holland", {})
        holland_start = 19
        for i, g in enumerate(holland.get("groups", [])):
            col = holland_start + i
            if col < len(sheets_scores):
                check(f"Holland_{g['id']}_total", sheets_scores[col], g["score"])
        if len(sheets_scores) > 28:
            check("Holland_top3", sheets_scores[28], ", ".join(holland.get("top3", [])))

        # OCEAN
        ocean       = expected.get("ocean", {})
        ocean_start = 29
        for i, g in enumerate(ocean.get("groups", [])):
            col = ocean_start + i
            if col < len(sheets_scores):
                check(f"OCEAN_{g['id']}_avg", sheets_scores[col], g["score"])

        # Composite scores
        for cs in expected.get("composite_scores", []):
            if cs["id"] == "sss" and len(sheets_scores) > 37:
                check("SSS",       sheets_scores[37], cs["score"])
                check("SSS_level", sheets_scores[38], cs["interpretation"])

        return passed

    def _get_last_row(self, sheet_name: str) -> int:
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self._sheet_id,
            range=f"'{sheet_name}'!A:A",
        ).execute()
        return len(result.get("values", []))

    def _write_row(self, sheet_name: str, row: int, values: list):
        self._service.spreadsheets().values().update(
            spreadsheetId=self._sheet_id,
            range=f"'{sheet_name}'!A{row}",
            valueInputOption="USER_ENTERED",
            body={"values": [values]},
        ).execute()

    def _delete_row(self, sheet_name: str, row: int):
        meta = self._service.spreadsheets().get(spreadsheetId=self._sheet_id).execute()
        sheet_id = next(
            s["properties"]["sheetId"]
            for s in meta["sheets"]
            if s["properties"]["title"] == sheet_name
        )
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId":    sheet_id,
                        "dimension":  "ROWS",
                        "startIndex": row - 1,
                        "endIndex":   row,
                    }
                }
            }]}
        ).execute()

    def _build_service(self):
        creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not creds_path:
            raise EnvironmentError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        return build("sheets", "v4", credentials=creds)
    
    def _center_row(self, sheet_name: str, row: int, num_cols: int):
        """Center align all cells in a row."""
        meta = self._service.spreadsheets().get(spreadsheetId=self._sheet_id).execute()
        sheet_id = next(
            s["properties"]["sheetId"]
            for s in meta["sheets"]
            if s["properties"]["title"] == sheet_name
        )
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._sheet_id,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId":          sheet_id,
                        "startRowIndex":    row - 1,
                        "endRowIndex":      row,
                        "startColumnIndex": 0,
                        "endColumnIndex":   num_cols,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat.horizontalAlignment"
                }
            }]}
        ).execute()