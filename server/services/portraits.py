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

TODO: Wire in data quality flags (Fatigue Risk, Speed Risk, Relevance Risk)
from the post-test UX survey once that data is available per-token.
Currently defaults to "không" for all three.

Cost: ~$0.05–$0.10 per call (Sonnet pricing: $3/$15 per 1M input/output tokens).
Model: Claude Sonnet 4.6 (sufficient for this shorter, structured task).
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import anthropic

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4000

PORTRAIT_PROMPT_FILE   = "portrait_prompt.md"
PORTRAIT_QUY_TRINH_FILE = "portrait_quy_trinh.md"

# Mirror Fit mapping per the SOP (Section VIII)
MIRROR_FIT = {
    "A": {"color": "Xanh",  "level": "High Fit",      "action": "viết chắc hơn"},
    "B": {"color": "Vàng",  "level": "Medium Fit",    "action": "đọc thêm nhánh phụ"},
    "C": {"color": "Cam",   "level": "Mismatch",      "action": "thêm cảnh báo + Quest"},
    "D": {"color": "Vàng",  "level": "Medium Fit",    "action": "đọc A và B, nhấn vùng giao"},
    "E": {"color": "Cam",   "level": "Check Fit",     "action": "đọc B và C, thêm Quest"},
    "F": {"color": "Cam",   "level": "Check Fit",     "action": "đọc A và C, thêm cảnh báo"},
    "G": {"color": "Đỏ",   "level": "Low Confidence", "action": "cần consultant review, viết mềm"},
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

    mbti    = scores["mbti"]
    holland = scores["holland"]
    ocean   = scores["ocean"]
    sss     = scores["sss"]
    axes    = mbti["axes"]

    # Fill in the student data block that replaces the [Điền] placeholders
    # in the PROMPT document's "Dữ liệu đầu vào" section
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
    match = re.search(
        r"Score-matched portrait[:\s]+([ABC])",
        text,
        re.IGNORECASE
    )
    if match:
        return match.group(1).upper()
    return None


def generate_portraits(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate 3 micro-portraits for the Mirror Check step.

    Returns:
        {
            "portrait_text": str,
            "score_matched": str | None,  # "A", "B", or "C"
            "model": str,
            "input_tokens": int,
            "output_tokens": int,
            "estimated_cost_usd": float,
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

    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    # Sonnet 4.6 pricing: $3/$15 per 1M input/output tokens
    cost = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)

    print(f"=== Portraits done — score_matched={score_matched} "
          f"input={input_tokens} output={output_tokens} cost=${round(cost, 4)} ===")
    print("=== PORTRAIT TEXT START ===")
    print(text)
    print("=== PORTRAIT TEXT END ===")

    return {
        "portrait_text": text,
        "score_matched": score_matched,
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }


def compute_mirror_fit(score_matched: str, student_choice: str) -> Dict[str, str]:
    """
    Compute Mirror Fit color and action per SOP Section VIII.

    Args:
        score_matched: which portrait the system considers core (A/B/C)
        student_choice: what the student actually chose (A/B/C/D/E/F/G)

    Returns:
        {"color": "Xanh"|"Vàng"|"Cam"|"Đỏ", "level": str, "action": str}
    """
    return MIRROR_FIT.get(
        student_choice.upper(),
        {"color": "Đỏ", "level": "Unknown", "action": "cần consultant review"}
    )


import os
import re
from typing import Any, Dict, Optional

import anthropic

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4000

# Mirror Fit mapping per the SOP (Section VIII)
MIRROR_FIT = {
    "A": {"color": "Xanh",  "level": "High Fit",     "action": "viết chắc hơn"},
    "B": {"color": "Vàng",  "level": "Medium Fit",   "action": "đọc thêm nhánh phụ"},
    "C": {"color": "Cam",   "level": "Mismatch",     "action": "thêm cảnh báo + Quest"},
    "D": {"color": "Vàng",  "level": "Medium Fit",   "action": "đọc A và B, nhấn vùng giao"},
    "E": {"color": "Cam",   "level": "Check Fit",    "action": "đọc B và C, thêm Quest"},
    "F": {"color": "Cam",   "level": "Check Fit",    "action": "đọc A và C, thêm cảnh báo"},
    "G": {"color": "Đỏ",   "level": "Low Confidence","action": "cần consultant review, viết mềm"},
}


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
        f"{top3[0]}={scores[0]} — {top3[1]}={scores[1]} "
        f"(chênh {gap_12} điểm)"
        + (f", {top3[2]}={scores[2]} (chênh {gap_23} điểm)" if len(scores) > 2 else "")
    )


def build_portrait_prompt(student_info: Dict[str, Any], scores: Dict[str, Any]) -> str:
    mbti    = scores["mbti"]
    holland = scores["holland"]
    ocean   = scores["ocean"]
    sss     = scores["sss"]

    axes = mbti["axes"]

    prompt = f"""Vai trò của bạn
Bạn là hệ thống phân tích hướng nghiệp An Du / META64. Nhiệm vụ của bạn là đọc kết quả tổng hợp từ bộ test 180 câu gồm MBTI, RIASEC/Holland và OCEAN, có thể kèm SSS, học bạ, raw response, feedback phụ huynh và data quality flags, để sinh ra 3 micro-portraits ngắn cho bước Mirror Check.

Mục tiêu
Sinh 3 micro-portraits để học sinh chọn bản mô tả đúng/giống mình nhất trước khi nhận full report.

Ba micro-portraits không phải là 3 ngành nghề. Ba micro-portraits là 3 giả thuyết chân dung vận hành:
- Portrait A – Score-matched / Core Portrait: Bản hệ thống dự đoán là khớp nhất với score tổng hợp.
- Portrait B – Neighbor Portrait: Bản láng giềng, vẫn có căn cứ từ score nhưng nhấn vào vùng điểm sát, trục mềm hoặc nhánh phụ.
- Portrait C – Tension / Check Portrait: Bản kiểm chứng vùng lệch hoặc vùng có thể bị test bỏ sót.

Nguyên tắc bắt buộc
- Không sinh micro-portrait chỉ từ MBTI.
- Không dùng MBTI để chốt ngành.
- Không sinh micro-portrait thành 3 nghề/ngành.
- Không dùng META64 một mình để sinh portrait.
- Không tạo option giả/sai rõ ràng trong UX chính thức.
- Không viết kiểu horoscope, khen chung chung.
- Mỗi portrait phải có căn cứ score rõ ràng.
- Mỗi portrait phải mô tả hành vi đời thực.
- Không để lộ thuật ngữ kỹ thuật cho học sinh: không nêu mã MBTI, RIASEC, OCEAN, META64 trong phần học sinh đọc (Sections II và III).
- Lựa chọn của học sinh không thay đổi điểm test gốc, chỉ dùng để đo Mirror Fit.

Dữ liệu đầu vào

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
- Fatigue Risk: không (chưa có dữ liệu từ post-test survey)
- Speed / Black-box Risk: không (chưa có dữ liệu từ post-test survey)
- Relevance Risk: không (chưa có dữ liệu từ post-test survey)
- Ghi chú data quality: Test lần đầu. Chưa có feedback phụ huynh. Chưa có dữ liệu UX từ phản hồi sau test.

Career Card nếu đã có: Chưa có — để AI suy luận từ score
META64 ver 2 nếu đã có: Chưa có — để AI suy luận từ score

Nhiệm vụ phân tích

Bước 1. Xác định lõi score
Hãy xác định: Holland/RIASEC core là gì. OCEAN đang chỉnh môi trường và độ bền như thế nào. SSS/social level cho thấy học sinh gần người dùng/người học/cộng đồng hay hậu trường. MBTI clarity có đủ mạnh để kể chân dung không, hay chỉ đọc mềm. Data quality có làm giảm độ chắc không. Raw response/học bạ/feedback có tín hiệu nào ủng hộ hoặc mâu thuẫn với scoring không.

Bước 2. Chọn portrait clusters
Portrait A – Core: Chọn cluster có độ khớp tổng hợp cao nhất với Holland + OCEAN + SSS + MBTI clarity + raw/học bạ.
Portrait B – Neighbor: Chọn cluster gần nhất với Portrait A nhưng khác trọng tâm, dựa trên điểm sát nhau, trục mềm hoặc nhánh phụ hợp lý.
Portrait C – Tension/Check: Chọn cluster phản ánh vùng lệch, vùng mâu thuẫn hoặc vùng có thể bị test bỏ sót.

Clusters có thể dùng: Deep Analyst, Structured Analyst, Creative Explorer, Creative Product Maker, User-aware Maker, Supportive Guide, Learning Content Builder, System Organizer, Operations Coordinator, Technical Builder, Data/Pattern Finder, Action Connector, Market Builder, Quiet Specialist, Adaptive Generalist.

Bước 3. Dùng Career Card và META64 để tinh chỉnh vai trò (suy luận từ score, không để lộ thuật ngữ ra ngoài Section II/III).

Bước 4. Viết 3 micro-portraits
Mỗi portrait dài 90–140 chữ, gồm 5 ý:
- Học sinh thường có năng lượng khi...
- Học sinh dễ làm tốt trong kiểu việc...
- Học sinh có thể bị kẹt khi...
- Học sinh hợp môi trường...
- Một hướng/Quest nhỏ nên thử để kiểm chứng...

Giọng văn: gần gũi, không quá người lớn, không đóng khung, không tâng bốc, không phán như định mệnh, không dùng thuật ngữ nặng, không dùng mã MBTI/RIASEC/OCEAN/META64. Dùng "có xu hướng", "dễ hợp hơn", "thường", "có thể".

Bước 5. Tạo phần lựa chọn cho học sinh (theo đúng định dạng bên dưới).

Bước 6. Tạo Consultant Note nội bộ (theo đúng định dạng bên dưới).

Định dạng output bắt buộc — trả về ĐÚNG cấu trúc sau, không thêm phần nào khác:

I. TÓM TẮT LOGIC SINH PORTRAIT
- Lõi score:
- OCEAN modifier:
- SSS/social modifier:
- MBTI clarity modifier:
- Raw/học bạ/feedback modifier:
- Data quality modifier:
- Career Card:
- META64 role layer:

II. 3 MICRO-PORTRAITS CHO HỌC SINH

A. [Tên portrait ngắn, dễ hiểu]
[Đoạn 90–140 chữ]

B. [Tên portrait ngắn, dễ hiểu]
[Đoạn 90–140 chữ]

C. [Tên portrait ngắn, dễ hiểu]
[Đoạn 90–140 chữ]

III. CÂU HỎI MIRROR CHECK CHO HỌC SINH

Trong 3 bản mô tả trên, bản nào giống em ngoài đời nhất, kể cả có điểm em chưa thích?

A. Bản A giống em nhất.
B. Bản B giống em nhất.
C. Bản C giống em nhất.
D. Em là pha giữa A và B.
E. Em là pha giữa B và C.
F. Em là pha giữa A và C.
G. Không bản nào giống em lắm.

Câu hỏi phụ:
- Câu nào trong bản em chọn làm em thấy "đúng là mình" nhất?
- Có câu nào em thấy không giống mình không?
- Em chọn bản này vì em đang như vậy ngoài đời, hay vì em muốn trở thành như vậy?

IV. CONSULTANT NOTE NỘI BỘ
- Portrait A cluster:
- Portrait B cluster:
- Portrait C cluster:
- Score-matched portrait: [phải là A, B, hoặc C — điền đúng chữ cái]
- Lý do score-matched:
- Neighbor logic:
- Tension/check logic:
- Data quality note:
- Nếu học sinh chọn A:
- Nếu học sinh chọn B:
- Nếu học sinh chọn C:
- Nếu học sinh chọn pha giữa:
- Nếu học sinh chọn "không bản nào giống em":
- Ảnh hưởng đến full report:
"""

    return prompt


def _parse_score_matched(text: str) -> Optional[str]:
    """
    Extract which portrait (A/B/C) is score-matched from the Consultant Note.
    Looks for 'Score-matched portrait: A/B/C' pattern.
    """
    match = re.search(
        r"Score-matched portrait[:\s]+([ABC])",
        text,
        re.IGNORECASE
    )
    if match:
        return match.group(1).upper()
    return None


def generate_portraits(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate 3 micro-portraits for the Mirror Check step.

    Returns:
        {
            "portrait_text": str,       # Full output (all 4 sections)
            "score_matched": str,       # "A", "B", or "C"
            "model": str,
            "input_tokens": int,
            "output_tokens": int,
            "estimated_cost_usd": float,
        }
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
    prompt = build_portrait_prompt(student_info, scores)

    print(f"=== Generating portraits for {student_info.get('name', '')} ===")

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(block.text for block in message.content if block.type == "text")
    score_matched = _parse_score_matched(text)

    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)

    print(f"=== Portraits done — score_matched={score_matched} "
          f"input={input_tokens} output={output_tokens} cost=${round(cost, 4)} ===")
    print("=== PORTRAIT TEXT START ===")
    print(text)
    print("=== PORTRAIT TEXT END ===")

    return {
        "portrait_text": text,
        "score_matched": score_matched,
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }


def compute_mirror_fit(score_matched: str, student_choice: str) -> Dict[str, str]:
    """
    Compute Mirror Fit color and action from the score-matched portrait
    and the student's self-selected choice (A-G).

    Per SOP Section VIII:
    - Student picks A (=score-matched) → Green
    - Student picks B (neighbor) → Yellow
    - Student picks C (tension) → Orange
    - Student picks D/E/F (blend) → Yellow or Orange depending on distance
    - Student picks G (none) → Red

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
