"""
server/services/report.py — AI career report generation (TEST/DEV)

Mirrors the real consultant workflow: feed the actual SOP document
(quy_trinh_chot_case.md) and the actual Master Router prompt template
(master_router_prompt.md), plus the Trong nước deep-dive prompt when
the case routes domestic — exactly the "3 file" pattern, not a
condensed rewrite.

Requires:
    ANTHROPIC_API_KEY environment variable
"""

import os
from pathlib import Path
from typing import Any, Dict

import anthropic

MODEL      = "claude-opus-4-7"
MAX_TOKENS = 8000

PROMPTS_DIRNAME = "prompts"
SOP_FILENAME           = "quy_trinh_chot_case.md"
MASTER_ROUTER_FILENAME  = "master_router_prompt.md"
TRONG_NUOC_FILENAME     = "prompt_2_5_trong_nuoc.md"

# Keywords used to detect route from the student's stated direction.
# This is a simple heuristic — Master Router itself also reasons about
# route internally, this just decides which extra file to attach.
OVERSEAS_KEYWORDS  = ["du học", "nước ngoài", "mỹ", "us", "uk", "canada", "úc", "australia"]
DOMESTIC_KEYWORDS  = ["trong nước", "việt nam", "học tiếp trong nước"]


def _get_prompts_dir() -> Path:
    """
    Find the src/prompts directory. Tries multiple candidate locations
    since the exact relative depth depends on how the Docker image was built.
    """
    here = Path(__file__).resolve()
    candidates = [
        Path("/app/src/prompts"),
        here.parent.parent / "src" / "prompts",
        here.parent.parent.parent / "src" / "prompts",
        Path.cwd() / "src" / "prompts",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Prompts directory not found. Tried: {[str(c) for c in candidates]}")


def _read_file(filename: str) -> str:
    path = _get_prompts_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return path.read_text(encoding="utf-8")


def _detect_route(direction: str) -> str:
    """Lightweight route detection from the student's stated direction field."""
    d = (direction or "").lower()
    if any(kw in d for kw in OVERSEAS_KEYWORDS):
        return "A"  # du học
    if any(kw in d for kw in DOMESTIC_KEYWORDS):
        return "B"  # trong nước
    return "C"  # chưa rõ — Master Router handles this branch internally


def build_prompt(student_info: Dict[str, Any], scores: Dict[str, Any]) -> str:
    sop           = _read_file(SOP_FILENAME)
    master_router = _read_file(MASTER_ROUTER_FILENAME)

    route = _detect_route(student_info.get("direction", ""))

    extra_branch_doc = ""
    if route == "B":
        extra_branch_doc = "\n\n---\n\n# TÀI LIỆU BỔ SUNG — SIÊU PROMPT 2.5 (TRONG NƯỚC)\n\n" + _read_file(TRONG_NUOC_FILENAME)

    transcript = student_info.get("transcript")
    transcript_line = f"\nHọc bạ (bằng chứng minh họa, không tự chốt hướng): {transcript}" if transcript else ""

    filled_fields = f"""
THÔNG TIN ĐIỀN VÀO MASTER ROUTER (thay cho các trường [Điền tên học sinh] v.v. ở trên):

Học sinh: {student_info.get('name', '')}
Lớp / tình trạng học tập: {student_info.get('grade', '')}
Bối cảnh đích đến: {student_info.get('direction', '')}
Dự định sau THPT: {student_info.get('after_school', '')}
Trường hiện tại: {student_info.get('school', '')}
Môn hợp vibe: {student_info.get('fav_subjects', '')}
Hoạt động yêu thích: {student_info.get('fav_activities', '')}
Tình trạng case: Test lần đầu
File đầu vào: File test (đã chấm điểm bên dưới){transcript_line}
Format cần viết theo: format An Du, đầy đủ Student Snapshot + Executive Summary + Consultant Note

DỮ LIỆU ĐÃ CHẤM ĐIỂM (không bịa thêm, không tính lại — đã verify):

MBTI: type={scores['mbti']['type']}, gap_avg={scores['mbti']['gap_avg']}, clarity={scores['mbti']['clarity']}
  Note: {scores['mbti']['note']}
  Axes: {scores['mbti']['axes']}

Holland: groups={scores['holland']['groups']}, top3={scores['holland']['top3']}

OCEAN: {scores['ocean']['groups']}

SSS: score={scores['sss']['score']}, level={scores['sss']['interpretation']}
"""

    task = """
NHIỆM VỤ:
Dùng đúng quy trình ở tài liệu "QUY TRÌNH CHỐT CASE" và format ở "SIÊU PROMPT 3.0 MASTER
ROUTER" phía trên (cùng với tài liệu bổ sung Trong Nước nếu có) để viết báo cáo hướng nghiệp
cá nhân đầy đủ cho học sinh này. Điền đúng route, chạy đúng chuỗi suy luận, không nhảy bước.
Không bịa tên trường/chương trình/số liệu nếu không chắc. Không cắt ngắn để tiết kiệm độ dài
— đây là báo cáo gửi gia đình thật.
"""

    return (
        "# TÀI LIỆU 1 — QUY TRÌNH CHỐT CASE\n\n" + sop +
        "\n\n---\n\n# TÀI LIỆU 2 — SIÊU PROMPT 3.0 MASTER ROUTER\n\n" + master_router +
        extra_branch_doc +
        "\n\n---\n\n# TÀI LIỆU 3 — DỮ LIỆU HỌC SINH VÀ NHIỆM VỤ\n\n" + filled_fields +
        "\n\n" + task
    )


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
