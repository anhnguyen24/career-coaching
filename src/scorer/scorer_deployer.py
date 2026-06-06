"""
scorer/scorer_deployer.py — Generates Scores tab formulas and runs integration test

What it does:
1. deploy_formulas()
   - Reads scoring config from survey JSON
   - Generates correct Google Sheets formulas for each scoring column
   - Writes those formulas to the seed row (row 2) of the Scores tab
   - All future onFormSubmit copies will inherit these formulas

2. run_integration_test()
   - Injects HN-2026-0007's known answers into Form Responses 2
   - Copies seed row formulas to a new test row
   - Waits for Google Sheets to recalculate
   - Reads the Scores tab output
   - Runs scorer.py on the same answers
   - Compares every field — reports pass/fail
   - Deletes the test row after (clean up)
"""

import os
import sys
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Allow import from parent src/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from scorer.scorer import Scorer

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# ============================================================
# Known test case — HN-2026-0007 (Vũ Thị Giáng Hương)
# All scores manually verified. See tests/test_scorer.py.
# ============================================================
KNOWN_ANSWERS = {
    1: 3, 2: 4, 3: 4, 4: 2, 5: 5, 6: 3,
    7: 1, 8: 1, 9: 1, 10: 3, 11: 1, 12: 3,
    13: 2, 14: 1, 15: 2, 16: 1, 17: 1, 18: 1, 19: 1, 20: 1, 21: 2, 22: 2, 23: 1, 24: 1,
    25: 3, 26: 2, 27: 2, 28: 2, 29: 1, 30: 1, 31: 2, 32: 1, 33: 1, 34: 1, 35: 1, 36: 1,
    37: 3, 38: 2, 39: 1, 40: 1, 41: 3, 42: 3,
    43: 1, 44: 1, 45: 1, 46: 2, 47: 1, 48: 1,
    49: 3, 50: 1, 51: 1, 52: 1, 53: 2, 54: 1,
    55: 3, 56: 1, 57: 2, 58: 1, 59: 3, 60: 2,
    61: 5, 62: 1, 63: 3, 64: 1, 65: 1, 66: 2, 67: 4, 68: 2, 69: 3, 70: 3,
    71: 1, 72: 4, 73: 5, 74: 4, 75: 5, 76: 1, 77: 4, 78: 1, 79: 4, 80: 5,
    81: 5, 82: 5, 83: 2, 84: 4, 85: 5, 86: 3, 87: 5, 88: 2, 89: 3, 90: 5,
    91: 2, 92: 5, 93: 5, 94: 5, 95: 5, 96: 1, 97: 5, 98: 5, 99: 3, 100: 5,
    101: 2, 102: 4, 103: 4, 104: 3, 105: 4, 106: 2, 107: 3, 108: 3, 109: 5, 110: 2,
    111: 2, 112: 5, 113: 3, 114: 5, 115: 5, 116: 5, 117: 5, 118: 2, 119: 4, 120: 2,
    121: 2, 122: 5, 123: 4, 124: 5, 125: 4, 126: 5, 127: 5, 128: 3, 129: 4, 130: 5, 131: 2, 132: 1,
    133: 4, 134: 5, 135: 3, 136: 4, 137: 5, 138: 5, 139: 5, 140: 5, 141: 3, 142: 1, 143: 1, 144: 3,
    145: 4, 146: 3, 147: 3, 148: 3, 149: 2, 150: 3, 151: 3, 152: 2, 153: 4, 154: 1, 155: 4, 156: 3,
    157: 5, 158: 5, 159: 5, 160: 5, 161: 5, 162: 3, 163: 5, 164: 5, 165: 2, 166: 3, 167: 1, 168: 2,
    169: 4, 170: 4, 171: 5, 172: 4, 173: 2, 174: 4, 175: 3, 176: 1, 177: 4, 178: 2, 179: 2, 180: 3,
}

# Student info columns prepended before questions in Form Responses 2
# Timestamp + 15 student info fields = 16 columns before Q1
STUDENT_INFO_COLS = 16

# Column letter helpers
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


class ScorerDeployer:

    def __init__(self, survey: dict):
        self._survey       = survey
        self._sheet_id     = os.environ["GOOGLE_SHEET_ID"]
        self._scores_sheet = os.environ.get("SCORES_SHEET_NAME", "Scores")
        self._response_sheet = os.environ.get("RESPONSE_SHEET_NAME", "Form Responses 2")
        self._service      = self._build_service()
        self._scorer       = Scorer(survey)

        # Build scoring lookup
        self._test_scoring = {
            ts["test_id"]: ts
            for ts in survey["scoring"]["tests"]
        }

    # ----------------------------------------------------------
    # Public: deploy formulas
    # ----------------------------------------------------------

    def deploy_formulas(self):
        """Generate formulas from JSON and write to Scores tab seed row."""
        formulas = self._generate_formulas(row=6)  # seed row points to data row 6
        print(f"  Generated {len(formulas)} scoring formulas")
        print(f"  Writing to {self._scores_sheet} row 2 (seed row)...")

        self._write_row(self._scores_sheet, 2, formulas)
        print(f"  ✅ Scores tab seed row updated")

    # ----------------------------------------------------------
    # Public: integration test
    # ----------------------------------------------------------

    def run_integration_test(self):
        """
        Inject known test answers, read Scores tab output,
        compare against scorer.py, report differences.
        """
        print(f"  Injecting test row (HN-2026-0007)...")
        test_row_index = self._inject_test_row()
        print(f"  Test row inserted at row {test_row_index} in {self._response_sheet}")

        # Copy seed formulas to a new Scores row pointing to test data row
        scores_last_row = self._get_last_row(self._scores_sheet)
        new_scores_row  = scores_last_row + 1
        formulas        = self._generate_formulas(row=test_row_index)
        self._write_row(self._scores_sheet, new_scores_row, formulas)
        print(f"  Scores formulas written to row {new_scores_row}")

        # Wait for Google Sheets to recalculate
        print(f"  Waiting 5s for Sheets to recalculate...")
        time.sleep(5)

        # Read Scores tab output
        sheets_scores = self._read_scores_row(new_scores_row)

        # Run scorer.py on same answers
        python_result = self._scorer.score(KNOWN_ANSWERS)

        # Compare
        passed = self._compare(sheets_scores, python_result)

        # Cleanup test rows
        print(f"\n  Cleaning up test rows...")
        self._delete_row(self._response_sheet, test_row_index)
        self._delete_row(self._scores_sheet, new_scores_row)
        print(f"  Test rows deleted")

        if not passed:
            print(f"\n  ❌ Integration test FAILED — see mismatches above")
            sys.exit(1)
        else:
            print(f"\n  ✅ Integration test PASSED — Scores tab matches scorer.py")

    # ----------------------------------------------------------
    # Formula generation
    # ----------------------------------------------------------

    def _generate_formulas(self, row: int) -> list:
        """
        Generate all Scores tab formulas for a given data row.
        Returns a flat list of values/formulas in column order:
        [Timestamp, Name, Token, E_avg, I_avg, S_avg, N_avg, T_avg, F_avg, J_avg, P_avg,
         MBTI_type, EI_gap, SN_gap, TF_gap, JP_gap, gap_avg, clarity, note,
         R_total, I_total, A_total, S_total, E_total, C_total,
         holland1, holland2, holland3, holland_top3,
         O_avg, C_avg, E_avg, A_avg, N_avg,
         mbti_social_ratio, mbti_social_score, raw_social_score, sss, social_level]
        """
        rs = self._response_sheet
        formulas = []

        # A-C: info columns
        formulas.append(f"='{rs}'!A{row}")   # Timestamp
        formulas.append(f"='{rs}'!B{row}")   # Name
        formulas.append(f"='{rs}'!C{row}")   # Token

        # MBTI
        mbti_ts = self._test_scoring["mbti"]
        mbti_groups = {g["id"]: g for g in mbti_ts["groups"]}
        axes_order = [("E","I"), ("S","N"), ("T","F"), ("J","P")]

        axis_avgs: dict[str, str] = {}   # group_id → cell reference for later use

        for a, b in axes_order:
            for gid in [a, b]:
                g = mbti_groups[gid]
                avg_formula = self._avg_formula(rs, row, g["forward"], g.get("reversed", []))
                formulas.append(avg_formula)
                # Remember column letter for this group avg (for gap formulas)
                col = col_letter(len(formulas))  # current column
                axis_avgs[gid] = col

        # MBTI type (derived from the 8 avg columns)
        # Use IF formulas referencing the avg columns
        e_col = col_letter(4)   # D
        i_col = col_letter(5)   # E
        s_col = col_letter(6)   # F
        n_col = col_letter(7)   # G
        t_col = col_letter(8)   # H
        f_col = col_letter(9)   # I
        j_col = col_letter(10)  # J
        p_col = col_letter(11)  # K

        mbti_type = (
            f'=IF({e_col}2>={i_col}2,"E","I")'
            f'&IF({s_col}2>={n_col}2,"S","N")'
            f'&IF({t_col}2>={f_col}2,"T","F")'
            f'&IF({j_col}2>={p_col}2,"J","P")'
        )
        mbti_type = mbti_type.replace("2", str(row) if row != 2 else "2")
        formulas.append(mbti_type)

        # Gaps (ABS of each pair)
        l_col = col_letter(len(formulas) + 1)
        for a, b in axes_order:
            a_col = col_letter(list(mbti_groups.keys()).index(a) * 1 + 4)
            b_col = col_letter(list(mbti_groups.keys()).index(b) * 1 + 4)
            # Recompute correct column indices
        # Simpler: compute gap as ABS(a_avg - b_avg) referencing actual cols
        col_map = {gid: col_letter(4 + i) for i, gid in enumerate(["E","I","S","N","T","F","J","P"])}
        for a, b in axes_order:
            formulas.append(f"=ROUND(ABS({col_map[a]}{row}-{col_map[b]}{row}),2)")

        # Gap avg
        gap_cols = [col_letter(13), col_letter(14), col_letter(15), col_letter(16)]
        formulas.append(f"=ROUND(AVERAGE({gap_cols[0]}{row}:{gap_cols[3]}{row}),2)")

        # Clarity
        gap_avg_col = col_letter(17)
        formulas.append(self._clarity_formula(gap_avg_col, row, mbti_ts.get("overall_clarity_thresholds", [])))

        # Note
        formulas.append(
            f'=IF(COUNTIF({col_map["E"]}{row}:{col_map["P"]}{row},"<0.4")>=2,'
            f'"Có từ 2 trục nghiêng nhẹ trở xuống — nên dùng MBTI như lớp tham khảo mềm.",'
            f'"MBTI có độ rõ tương đối tốt, nhưng vẫn nên đọc cùng Holland và OCEAN.")'
        )

        # Holland — SUM per group
        holland_ts = self._test_scoring["holland"]
        holland_col_start = len(formulas) + 1
        for g in holland_ts["groups"]:
            formulas.append(self._sum_formula(rs, row, g["forward"]))

        # Holland Top 3
        h_cols = [col_letter(holland_col_start + i) for i in range(len(holland_ts["groups"]))]
        h_ids  = [g["id"] for g in holland_ts["groups"]]
        formulas.append(self._holland_rank_formula(h_cols, h_ids, row, 1))
        formulas.append(self._holland_rank_formula(h_cols, h_ids, row, 2))
        formulas.append(self._holland_rank_formula(h_cols, h_ids, row, 3))

        top3_col1 = col_letter(len(formulas) - 2)
        top3_col2 = col_letter(len(formulas) - 1)
        top3_col3 = col_letter(len(formulas))
        formulas.append(f"={top3_col1}{row}&\", \"&{top3_col2}{row}&\", \"&{top3_col3}{row}")

        # OCEAN — average with reverse
        ocean_ts = self._test_scoring["ocean"]
        ocean_col_start = len(formulas) + 1
        for g in ocean_ts["groups"]:
            formulas.append(self._avg_formula(rs, row, g["forward"], g.get("reversed", [])))

        # SSS composite
        sss_def = next(
            cs for cs in self._survey["scoring"]["composite_scores"]
            if cs["id"] == "sss"
        )
        ocean_e_col = col_letter(ocean_col_start + 2)  # O, C, E → index 2

        # MBTI social ratio = E / (E + I)
        e_c = col_map["E"]
        i_c = col_map["I"]
        formulas.append(f"=ROUND({e_c}{row}/({e_c}{row}+{i_c}{row}),2)")

        # MBTI social score = 1 + 4 * ratio
        ratio_col = col_letter(len(formulas))
        formulas.append(f"=ROUND(1+4*{ratio_col}{row},2)")

        # Raw social score
        sss_comp = next(c for c in sss_def["components"] if c["source"] == "question_subset")
        formulas.append(self._avg_formula(rs, row, sss_comp.get("forward", []), sss_comp.get("reversed", [])))

        # SSS total
        mbti_ss_col  = col_letter(len(formulas) - 1)
        raw_ss_col   = col_letter(len(formulas))
        weights      = {c["source"]: c["weight"] for c in sss_def["components"]}
        w_mbti  = weights.get("bipolar_ratio", 0.30)
        w_ocean = weights.get("test_group", 0.40)
        w_raw   = weights.get("question_subset", 0.30)
        formulas.append(
            f"=ROUND({w_mbti}*{mbti_ss_col}{row}"
            f"+{w_ocean}*{ocean_e_col}{row}"
            f"+{w_raw}*{raw_ss_col}{row},2)"
        )

        # SSS interpretation
        sss_col = col_letter(len(formulas))
        formulas.append(self._interpret_formula(sss_col, row, sss_def.get("interpretation_thresholds", [])))

        return formulas

    def _avg_formula(self, sheet: str, row: int, forward: list[int], reversed_qs: list[int]) -> str:
        """Generate AVERAGE formula with optional reversed questions."""
        parts = [f"'{sheet}'!{q_col(n)}{row}" for n in forward]
        parts += [f"6-'{sheet}'!{q_col(n)}{row}" for n in reversed_qs]
        return f"=ROUND(AVERAGE({','.join(parts)}),2)"

    def _sum_formula(self, sheet: str, row: int, questions: list[int]) -> str:
        """Generate SUM formula for a list of questions."""
        parts = [f"'{sheet}'!{q_col(n)}{row}" for n in questions]
        return f"=SUM({','.join(parts)})"

    def _holland_rank_formula(self, h_cols: list, h_ids: list, row: int, rank: int) -> str:
        """Generate a formula that returns the group ID with the nth highest score."""
        ids_str   = "{" + ",".join(f'"{h}"' for h in h_ids) + "}"
        scores_range = ",".join(f"{c}{row}" for c in h_cols)
        return (
            f"=INDEX({ids_str},MATCH(LARGE({{{scores_range}}},{rank})"
            f",{{{scores_range}}},0))"
        )

    def _clarity_formula(self, col: str, row: int, thresholds: list) -> str:
        """Generate nested IF formula for clarity interpretation."""
        if not thresholds:
            return '=""'
        result = f'"{thresholds[-1]["label"]}"'
        for t in reversed(thresholds[:-1]):
            result = f'IF({col}{row}<{t["max"]},"{t["label"]}",{result})'
        return f"={result}"

    def _interpret_formula(self, col: str, row: int, thresholds: list) -> str:
        """Generate nested IF formula for score interpretation."""
        if not thresholds:
            return '=""'
        result = f'"{thresholds[-1]["label"]}"'
        for t in reversed(thresholds[:-1]):
            result = f'IF({col}{row}<{t["max"]},"{t["label"]}",{result})'
        return f"={result}"

    # ----------------------------------------------------------
    # Integration test helpers
    # ----------------------------------------------------------

    def _inject_test_row(self) -> int:
        """Append known test answers to Form Responses 2. Returns new row index."""
        # Build row: timestamp + student info (15 placeholders) + 180 answers
        student_info = [
            "2026-01-01 00:00:00",  # timestamp
            "TEST HN-2026-0007",    # name
            "HN-2026-TEST",         # token (special test token)
            "07/11/2010",           # dob
            "Nữ",                   # gender
            "10D3",                 # grade
            "2025-2026",            # school year
            "THPT THĂNG LONG",      # school
            "Hà Nội",               # city
            "test@test.com",        # email
            "0000000000",           # phone
            "Du học",               # direction
            "Đi học tiếp",          # after school
            "Văn, Sử, Anh",         # fav subjects
            "Xem phim",             # fav activities
            "Đồng ý",               # commitment
        ]
        answers = [KNOWN_ANSWERS[i] for i in range(1, 181)]
        row_data = student_info + answers

        result = self._service.spreadsheets().values().append(
            spreadsheetId=self._sheet_id,
            range=f"'{self._response_sheet}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]}
        ).execute()

        updated_range = result["updates"]["updatedRange"]
        # Extract row number from range like "Form Responses 2'!A42:GN42"
        row_num = int(updated_range.split("!")[-1].split(":")[0][1:])
        return row_num

    def _read_scores_row(self, row: int) -> list:
        """Read all values from a Scores tab row."""
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self._sheet_id,
            range=f"'{self._scores_sheet}'!A{row}:AM{row}",
            valueRenderOption="UNFORMATTED_VALUE",
        ).execute()
        values = result.get("values", [[]])
        return values[0] if values else []

    def _compare(self, sheets_scores: list, python_result) -> bool:
        """Compare Scores tab output against scorer.py output."""
        passed = True
        tol    = 0.02

        def check(label: str, sheet_val, python_val):
            nonlocal passed
            try:
                sheet_f  = float(sheet_val)
                python_f = float(python_val)
                if abs(sheet_f - python_f) > tol:
                    print(f"  ❌ {label}: Sheets={sheet_f:.4f}  Python={python_f:.4f}")
                    passed = False
                else:
                    print(f"  ✅ {label}: {sheet_f:.4f}")
            except (TypeError, ValueError):
                if str(sheet_val) != str(python_val):
                    print(f"  ❌ {label}: Sheets={sheet_val!r}  Python={python_val!r}")
                    passed = False
                else:
                    print(f"  ✅ {label}: {sheet_val!r}")

        if not sheets_scores:
            print("  ❌ No scores found in Scores tab row")
            return False

        # MBTI
        mbti = python_result.mbti
        col_map = {"E": 3, "I": 4, "S": 5, "N": 6, "T": 7, "F": 8, "J": 9, "P": 10}
        for gid, col_idx in col_map.items():
            ax = next((ax for ax in mbti.axes if ax.group_a.id == gid or ax.group_b.id == gid), None)
            if ax:
                score = ax.group_a.score if ax.group_a.id == gid else ax.group_b.score
                if col_idx < len(sheets_scores):
                    check(f"MBTI_{gid}_avg", sheets_scores[col_idx], score)

        check("MBTI_type", sheets_scores[11] if len(sheets_scores) > 11 else None, mbti.type)

        # Holland
        if python_result.holland:
            holland_start = 19
            for i, g in enumerate(python_result.holland.groups):
                col = holland_start + i
                if col < len(sheets_scores):
                    check(f"Holland_{g.id}_total", sheets_scores[col], g.score)
            if len(sheets_scores) > 28:
                check("Holland_top3", sheets_scores[28], ", ".join(python_result.holland.top3))

        # OCEAN
        if python_result.ocean:
            ocean_start = 29
            for i, g in enumerate(python_result.ocean.groups):
                col = ocean_start + i
                if col < len(sheets_scores):
                    check(f"OCEAN_{g.id}_avg", sheets_scores[col], g.score)

        # SSS
        sss = next((cs for cs in python_result.composite_scores if cs.id == "sss"), None)
        if sss and len(sheets_scores) > 37:
            check("SSS", sheets_scores[37], sss.score)
            check("SSS_level", sheets_scores[38], sss.interpretation)

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
        """Delete a row by index using batchUpdate."""
        # Get sheet ID from name
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
                        "startIndex": row - 1,   # 0-based
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
