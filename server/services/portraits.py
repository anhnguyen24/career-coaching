"""
server/services/portraits.py — Micro-portrait generation for Mirror Check step

Generates 3 micro-portraits (Score-matched, Neighbor, Tension/Check) from
student scores, using the exact prompt documents from:
  src/prompts/portrait_prompt.md     — PROMPT SINH 3 MICRO-PORTRAITS
  src/prompts/portrait_quy_trinh.md  — QUY TRÌNH SINH 3 MICRO-PORTRAITS

Output is a plain-text response with four clearly delimited sections:
  I.  TÓM TẮT LOGIC SINH PORTRAIT
  II. 3 MICRO-PORTRAITS CHO HỌC SINH
  III.CÂU HỎI MIRROR CHECK CHO HỌC SINH
  IV. CONSULTANT NOTE NỘI BỘ

Sections II and III are student-facing (no MBTI/RIASEC/OCEAN codes).
Sections I and IV are consultant-only.

The raw text is split into these 4 sections here (backend), not by callers
(e.g. Apps Script) — this keeps the section-header format as a single
source of truth. If portrait_prompt.md's required output headers ever
change, only _parse_sections() below needs updating.

TODO: Wire in data quality flags (Fatigue Risk, Speed Risk, Relevance Risk)
from the post-test UX survey once that data is available per-token.
Currently defaults to "không" for all three.

Cost: ~$0.05–$0.12 per call (Sonnet pricing: $3/$15 per 1M input/output tokens).
Model: Claude Sonnet 4.6 (sufficient for this shorter, structured task).
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import anthropic

MODEL = "claude-sonnet-4-6"

# NOTE: 4000 was too tight — real outputs (Sections I-IV, Vietnamese) were
# hitting this cap and getting cut off mid-sentence before Section IV ever
# closed. Raised to 8000 to give the full 4-section output headroom.
MAX_TOKENS = 8000

PORTRAIT_PROMPT_FILE = "portrait_prompt.md"
PORTRAIT_QUY_TRINH_FILE = "portrait_quy_trinh.md"

# Mirror Fit mapping per the SOP (Section VIII)
MIRROR_FIT = {
    "A": {"color": "Xanh", "level": "High Fit", "action": "viết chắc hơn"},
    "B": {"color": "Vàng", "level": "Medium Fit", "action": "đọc thêm nhánh phụ"},
    "C": {"color": "Cam", "level": "Mismatch", "action": "thêm cảnh báo + Quest"},
    "D": {"color": "Vàng", "level": "Medium Fit", "action": "đọc A và B, nhấn vùng giao"},
    "E": {"color": "Cam", "level": "Check Fit", "action": "đọc B và C, thêm Quest"},
    "F": {"color": "Cam", "level": "Check Fit", "action": "đọc A và C, thêm cảnh báo"},
    "G": {"color": "Đỏ", "level": "Low Confidence", "action": "cần consultant review, viết mềm"},
}


def _get_prompts_dir() -> Path:
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


def _read_prompt_file(filename: str) -> str:
    path = _get_prompts_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Portrait prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _sss_label(sss_score: float) -> str:
    if sss_score < 2.4:
        return "thấp — hợp hậu trường/product-facing, không hợp public-facing/sales-facing"
    if sss_score < 3.2:
        return "trung bình — hợp user-facing/student-facing vừa phải, không hợp public-facing dày"
    return "cao — hợp student-facing/public-facing/support-facing"


def _mbti_note(gap_avg: float) -> str:
    if gap_avg < 0.40:
        return "đọc mềm — nhiều trục lưng chừng, chỉ dùng như tham khảo nhẹ"
    if gap_avg < 0.70:
        return "đọc vừa — có thể kể chân dung nhưng tránh đóng khung"
    return "đọc mạnh — đủ rõ để kể chân dung"


def _axis_clarity(gap: float) -> str:
    if gap < 0.20:
        return "rất lưng chừng"
    if gap < 0.40:
        return "nghiêng nhẹ"
    if gap < 0.70:
        return "nghiêng vừa"
    return "khá rõ"


def _holland_gap_note(groups: Dict[str, float], top3: list) -> str:
    """Describe gap between top3 Holland scores for the prompt."""
    if len(top3) < 2:
        return "chỉ có 1 mã rõ"
    scores = [groups.get(code, 0) for code in top3]
    gap_12 = round(scores[0] - scores[1], 1)
    gap_23 = round(scores[1] - scores[2], 1) if len(scores) > 2 else 0
    return (
        f"{top3[0]}={scores[0]} — {top3[1]}={scores[1]} (chênh {gap_12} điểm)"
        + (f", {top3[2]}={scores[2]} (chênh {gap_23} điểm)" if len(scores) > 2 else "")
    )


def build_portrait_prompt(student_info: Dict[str, Any], scores: Dict[str, Any]) -> str:
    """
    Assemble the full prompt by combining:
    1. The QUY TRINH document (methodology/principles)
    2. The PROMPT document (exact fill-in-the-blank template with student data)
    """
    quy_trinh = _read_prompt_file(PORTRAIT_QUY_TRINH_FILE)
    prompt_template = _read_prompt_file(PORTRAIT_PROMPT_FILE)

    mbti = scores["mbti"]
    holland = scores["holland"]
    ocean = scores["ocean"]
    sss = scores["sss"]
    axes = mbti["axes"]

    filled_data = f"""
---
DỮ LIỆU ĐẦU VÀO (điền vào các trường [Điền] trong prompt trên)

Học sinh: {student_info.get("name", "")}
Lớp / tình trạng học tập: {student_info.get("grade", "")} — {student_info.get("school", "")}
Bối cảnh đích đến: {student_info.get("direction", "Chưa rõ")}

MBTI:
- Type: {mbti["type"]}
- EI clarity: {_axis_clarity(axes["EI"]["gap"])} (E={axes["EI"]["scores"]["E"]}, I={axes["EI"]["scores"]["I"]}, gap={axes["EI"]["gap"]})
- SN clarity: {_axis_clarity(axes["SN"]["gap"])} (S={axes["SN"]["scores"]["S"]}, N={axes["SN"]["scores"]["N"]}, gap={axes["SN"]["gap"]})
- TF clarity: {_axis_clarity(axes["TF"]["gap"])} (T={axes["TF"]["scores"]["T"]}, F={axes["TF"]["scores"]["F"]}, gap={axes["TF"]["gap"]})
- JP clarity: {_axis_clarity(axes["JP"]["gap"])} (J={axes["JP"]["scores"]["J"]}, P={axes["JP"]["scores"]["P"]}, gap={axes["JP"]["gap"]})
- Overall clarity: {mbti["clarity"]} (gap_avg={mbti["gap_avg"]})
- MBTI note: {_mbti_note(mbti["gap_avg"])}

RIASEC / Holland:
- R: {holland["groups"]["R"]}
- I: {holland["groups"]["I"]}
- A: {holland["groups"]["A"]}
- S: {holland["groups"]["S"]}
- E: {holland["groups"]["E"]}
- C: {holland["groups"]["C"]}
- Top 3: {" — ".join(holland["top3"])} | Label: {holland["top3_label"]}
- Khoảng cách giữa các điểm top: {_holland_gap_note(holland["groups"], holland["top3"])}

OCEAN:
- O (Openness): {ocean["groups"]["O"]}
- C (Conscientiousness): {ocean["groups"]["C"]}
- E (Extraversion): {ocean["groups"]["E"]}
- A (Agreeableness): {ocean["groups"]["A"]}
- N (Neuroticism): {ocean["groups"]["N"]}

SSS / Social Sync:
- SSS score: {sss["score"]}
- Social level: {sss["interpretation"]}
- Diễn giải: {_sss_label(sss["score"])}

Học bạ / môn hợp vibe: {student_info.get("fav_subjects", "Không có thông tin")}
Raw response / sở thích / hoạt động yêu thích: {student_info.get("fav_activities", "Không có thông tin")}
Định hướng sau THPT: {student_info.get("after_school", "Không có thông tin")}
Feedback phụ huynh / quan sát đời thực nếu có: Không có

Data Quality Flags:
- Fatigue Risk: không (chưa có dữ liệu từ post-test survey — TODO: wire in later)
- Speed / Black-box Risk: không (chưa có dữ liệu từ post-test survey)
- Relevance Risk: không (chưa có dữ liệu từ post-test survey)
- Ghi chú data quality: Test lần đầu. Chưa có feedback phụ huynh. Chưa có dữ liệu UX từ phản hồi sau test.

Career Card nếu đã có: Chưa có — để AI suy luận từ score
META64 ver 2 nếu đã có: Chưa có — để AI suy luận từ score
"""

    task = """
---
NHIỆM VỤ
Thực hiện đúng các bước phân tích trong QUY TRÌNH và PROMPT ở trên với dữ liệu học sinh đã điền.
Trả output theo ĐÚNG định dạng bắt buộc trong PROMPT (4 phần: I. TÓM TẮT LOGIC, II. 3 MICRO-PORTRAITS, III. CÂU HỎI MIRROR CHECK, IV. CONSULTANT NOTE).
Không thêm phần nào khác. Không để lộ mã MBTI/RIASEC/OCEAN/META64 trong Sections II và III.
"""

    return (
        "# TÀI LIỆU 1 — QUY TRÌNH SINH 3 MICRO-PORTRAITS\n\n" + quy_trinh +
        "\n\n---\n\n# TÀI LIỆU 2 — PROMPT SINH 3 MICRO-PORTRAITS\n\n" + prompt_template +
        filled_data +
        task
    )


def _parse_score_matched(text: str) -> Optional[str]:
    """
    Extract which portrait (A/B/C) is score-matched from the Consultant Note.

    The model reliably outputs a line like:
        - Score-matched portrait: A
    or, since it's writing markdown, often:
        - **Score-matched portrait:** A

    The old regex (`Score-matched portrait[:\\s]+([ABC])`) required a colon
    or whitespace to appear immediately after the word "portrait". With
    markdown bold, "portrait" is immediately followed by "**" before the
    colon, so the match silently failed on real (non-truncated) output.
    This version tolerates any markdown punctuation (*, _, whitespace, :)
    between "portrait" and the letter.
    """
    match = re.search(
        r"Score-matched portrait[\*_\s:]+([ABC])\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


# Section headers exactly as specified in portrait_prompt.md's required
# output format. Splitting happens here (backend) rather than in Apps
# Script so there is a single source of truth for the format — if the
# prompt's headers ever change, only this needs updating, not every
# downstream consumer (Apps Script, future admin UI, etc).
_SECTION_PATTERNS = {
    "I": re.compile(r"I\.\s*TÓM TẮT LOGIC SINH PORTRAIT", re.IGNORECASE),
    "II": re.compile(r"II\.\s*3 MICRO-PORTRAITS CHO HỌC SINH", re.IGNORECASE),
    "III": re.compile(r"III\.\s*CÂU HỎI MIRROR CHECK CHO HỌC SINH", re.IGNORECASE),
    "IV": re.compile(r"IV\.\s*CONSULTANT NOTE NỘI BỘ", re.IGNORECASE),
}
_SECTION_ORDER = ["I", "II", "III", "IV"]


def _parse_sections(text: str) -> Dict[str, str]:
    """
    Split the raw portrait_text into its 4 defined sections:
      I   — Logic summary (consultant-only)
      II  — 3 micro-portraits (student-facing, no MBTI/RIASEC/OCEAN codes)
      III — Mirror Check question + follow-ups (student-facing)
      IV  — Consultant note (consultant-only)

    Matching is done by locating each section's fixed header text and
    slicing up to the next section's header (or end of string for the
    last section present). If a header isn't found — e.g. the response
    was truncated before that section was written — that section comes
    back as an empty string rather than raising, so callers can still
    use whatever sections did generate successfully.
    """
    starts: Dict[str, int] = {}
    for key, pattern in _SECTION_PATTERNS.items():
        match = pattern.search(text)
        if match:
            starts[key] = match.start()

    sections: Dict[str, str] = {key: "" for key in _SECTION_ORDER}

    present_keys = [k for k in _SECTION_ORDER if k in starts]
    for i, key in enumerate(present_keys):
        start = starts[key]
        end = starts[present_keys[i + 1]] if i + 1 < len(present_keys) else len(text)
        sections[key] = text[start:end].strip()

    return sections


def generate_portraits(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate 3 micro-portraits for the Mirror Check step.

    Returns:
        {
            "portrait_text": str,          # full raw output — used for the doc
            "score_matched": str | None,   # "A", "B", or "C"
            "logic_summary": str,          # Section I — consultant-only
            "student_portraits": str,      # Section II — student-facing
            "mirror_question": str,        # Section III — student-facing
            "consultant_note": str,        # Section IV — consultant-only
            "model": str,
            "input_tokens": int,
            "output_tokens": int,
            "estimated_cost_usd": float,
            "truncated": bool,             # True if generation hit MAX_TOKENS
        }
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
    prompt = build_portrait_prompt(student_info, scores)

    print(f"=== Generating portraits for {student_info.get('name', '')} "
          f"(prompt length: {len(prompt)} chars) ===")

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")
    score_matched = _parse_score_matched(text)
    sections = _parse_sections(text)
    truncated = message.stop_reason == "max_tokens"

    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)

    print(f"=== Portraits done — score_matched={score_matched} "
          f"input={input_tokens} output={output_tokens} "
          f"stop_reason={message.stop_reason} cost=${round(cost, 4)} ===")
    if truncated:
        print("=== WARNING: response hit MAX_TOKENS and was truncated ===")
    missing_sections = [k for k in _SECTION_ORDER if not sections[k]]
    if missing_sections:
        print(f"=== WARNING: sections not found in output: {missing_sections} "
              f"(likely truncation or a prompt format change) ===")
    print("=== PORTRAIT TEXT START ===")
    print(text)
    print("=== PORTRAIT TEXT END ===")

    return {
        "portrait_text": text,
        "score_matched": score_matched,
        "logic_summary": sections["I"],
        "student_portraits": sections["II"],
        "mirror_question": sections["III"],
        "consultant_note": sections["IV"],
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "truncated": truncated,
    }


def compute_mirror_fit(score_matched: str, student_choice: str) -> Dict[str, str]:
    """
    Compute Mirror Fit color and action from the score-matched portrait
    and the student's self-selected choice (A-G), per SOP Section VIII.

    Args:
        score_matched: which portrait is A/B/C (what the system predicted)
        student_choice: what the student actually chose (A/B/C/D/E/F/G)

    Returns:
        {"color": "Xanh"|"Vàng"|"Cam"|"Đỏ", "level": str, "action": str}
    """
    return MIRROR_FIT.get(
        student_choice.upper(),
        {"color": "Đỏ", "level": "Unknown", "action": "cần consultant review"}
    )
