"""
server/services/report.py — AI career report generation (TEST/DEV)

Calls the real Anthropic API directly with the full SOP and real
student scores, using Claude Opus with a generous token budget.

Purpose: measure real cost and quality before committing to a
production architecture. This is NOT wired into the student-facing
pipeline yet — Apps Script still owns doc creation for now.

Requires:
    ANTHROPIC_API_KEY environment variable
"""

import os
from pathlib import Path
from typing import Any, Dict

import anthropic

MODEL      = "claude-opus-4-7"
MAX_TOKENS = 8000


def _get_sop_path() -> Path:
    """
    Find the SOP file. Tries multiple candidate locations since the
    exact relative depth depends on how the Docker image was built.
    """
    here = Path(__file__).resolve()
    candidates = [
        Path("/app/src/prompts/career_report_sop.md"),
        here.parent.parent / "src" / "prompts" / "career_report_sop.md",
        here.parent.parent.parent / "src" / "prompts" / "career_report_sop.md",
        Path.cwd() / "src" / "prompts" / "career_report_sop.md",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"SOP file not found. Tried: {[str(c) for c in candidates]}")


def _load_sop() -> str:
    path = _get_sop_path()
    return path.read_text(encoding="utf-8")


def build_prompt(student_info: Dict[str, Any], scores: Dict[str, Any]) -> str:
    sop = _load_sop()

    data_block = f"""
DỮ LIỆU HỌC SINH (đã chấm điểm, không bịa thêm):

Họ tên: {student_info.get('name', '')}
Lớp: {student_info.get('grade', '')}
Trường: {student_info.get('school', '')}
Định hướng: {student_info.get('direction', '')}
Dự định sau THPT: {student_info.get('after_school', '')}
Môn hợp vibe: {student_info.get('fav_subjects', '')}
Hoạt động yêu thích: {student_info.get('fav_activities', '')}

MBTI: type={scores['mbti']['type']}, gap_avg={scores['mbti']['gap_avg']}, clarity={scores['mbti']['clarity']}
  Note: {scores['mbti']['note']}
  Axes: {scores['mbti']['axes']}

Holland: groups={scores['holland']['groups']}, top3={scores['holland']['top3']}

OCEAN: {scores['ocean']['groups']}

SSS: score={scores['sss']['score']}, level={scores['sss']['interpretation']}
"""

    task = """
NHIỆM VỤ:
Viết báo cáo hướng nghiệp đầy đủ theo đúng cấu trúc Phần 4 của SOP ở trên (AUDIT NỘI BỘ,
PHẦN A, PHẦN B). Tuân thủ nghiêm ngặt mọi quy tắc đã nêu, đặc biệt luật MBTI, luật Holland,
và route logic.
"""

    return sop + "\n\n" + data_block + "\n\n" + task


def generate_report(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(student_info, scores)

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")

    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 5) + (output_tokens / 1_000_000 * 25)

    return {
        "report_text": text,
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }
