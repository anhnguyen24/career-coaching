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

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator

import anthropic
from docx import Document
from docx.shared import Pt

MODEL      = "claude-opus-4-7"
MAX_TOKENS = 20000

PROMPTS_DIRNAME = "prompts"
SOP_FILENAME           = "quy_trinh_chot_case.md"
MASTER_ROUTER_FILENAME  = "master_router_prompt.md"
TRONG_NUOC_FILENAME     = "prompt_2_5_trong_nuoc.md"

# Exact match against the live form's dropdown options for
# "Bạn đang quan tâm hướng nào nhất?" — confirmed from the actual form
# (not fuzzy keywords, to avoid silent misrouting if wording is close
# but not identical, e.g. "Chọn ngành đại học ở VN" vs guessed "trong nước").
#
# NOTE: "Học nghề/College" is mapped to Route B (domestic) as a judgment
# call — it's a domestic vocational/college track, but the SOP files may
# not explicitly address vocational pathways the same way as university
# pathways. Revisit if this doesn't read correctly in testing.
ROUTE_BY_DIRECTION = {
    "du học":                  "A",
    "chọn ngành đại học ở vn": "B",
    "học nghề/college":        "B",
    "chưa rõ, đang tìm hiểu":  "C",
}


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
    """
    Exact-match route detection against real form dropdown values.
    Unknown/unexpected values default to "C" (chưa rõ) rather than
    guessing — safer than silently misrouting, and Route C is already
    designed to handle ambiguity per the SOP.
    """
    key = (direction or "").strip().lower()
    return ROUTE_BY_DIRECTION.get(key, "C")


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

YÊU CẦU BẮT BUỘC VỀ CẤU TRÚC ĐẦU RA (áp dụng thêm, ngoài quy trình ở trên):

1. **KHÔNG in 4 chữ MBTI (ví dụ "ENTP") trong [PHẦN A] hoặc [PHẦN B] gửi học sinh/phụ huynh.**
   MBTI type chỉ được nêu tên trong [AUDIT NỘI BỘ]. Phần gửi gia đình chỉ tả tính cách bằng
   ngôn ngữ thường ("em có xu hướng...", "em hợp kiểu..."), không gắn nhãn 4 chữ cái.

2. **Xếp hạng major family/vùng nghề ưu tiên #1 phải tương ứng với mã Holland điểm cao nhất**
   trong Top 3, trừ khi có lý do rõ từ OCEAN/SSS/bối cảnh để hạ xuống — nếu đảo thứ tự, phải
   nêu lý do cụ thể trong [AUDIT NỘI BỘ].

3. **Phải có [TÊN ĐỌC RIÊNG]** — một cụm từ ngắn (4-6 chữ), giàu hình ảnh, tóm gọn cách học
   sinh tạo giá trị (không phải tên nghề, không phải nhãn tính cách). Sau tên, viết 2-3 câu
   giải thích, làm rõ tên này không ép học sinh vào một nghề cố định.

4. **Mỗi major family/vùng nghề đề xuất phải được đào sâu đầy đủ**, không chỉ liệt kê tên:
   - Vì sao hợp (nối tới Holland/OCEAN/SSS/bối cảnh cụ thể của học sinh này)
   - Ngành này học gì (course content thực tế, không bịa tên trường cụ thể)
   - Việc thường gặp sau khi ra trường (5-8 việc cụ thể)
   - Vai trò nghề có thể hướng tới (3-5 chức danh cụ thể)
   - Mức ưu tiên (Rất cao / Cao / Khá cao / Có điều kiện / Trung bình) kèm lý do ngắn

5. **Phải có "Application Story Themes"** trong Phần B — 3-4 trục câu chuyện cho personal
   statement, mỗi trục 2-3 câu, gắn cụ thể vào dữ liệu/bối cảnh thật của học sinh này (không
   viết chung chung kiểu "em rất thích giúp người").

6. **Phải có "Hồ sơ nên có"** trong Phần B — personal statement nên xoay quanh chủ đề gì,
   loại portfolio/hoạt động nên có, loại project nên làm, hướng thư giới thiệu nên nhấn vào
   điều gì.

7. **Phải có [LỜI KẾT GỬI PHỤ HUYNH]** ở cuối — đoạn ngắn (4-6 câu) tóm gọn tinh thần báo
   cáo: đây là bản đồ mở không phải bản án; nhấn lại điểm mạnh cốt lõi; nhắc gia đình tránh
   đẩy con theo hướng ngược với dữ liệu.
"""

    return (
        "# TÀI LIỆU 1 — QUY TRÌNH CHỐT CASE\n\n" + sop +
        "\n\n---\n\n# TÀI LIỆU 2 — SIÊU PROMPT 3.0 MASTER ROUTER\n\n" + master_router +
        extra_branch_doc +
        "\n\n---\n\n# TÀI LIỆU 3 — DỮ LIỆU HỌC SINH VÀ NHIỆM VỤ\n\n" + filled_fields +
        "\n\n" + task
    )


_REFERENCE_DOCX_CACHE: Path | None = None


def _get_reference_docx() -> Path:
    """
    Build (once, cached) a .docx with Arial set as the default font for
    Normal and Heading styles, used as pandoc's --reference-doc.

    IMPORTANT: starts from pandoc's OWN default reference doc (via
    `pandoc --print-default-data-file reference.docx`), not a blank
    python-docx Document(). A blank python-docx document lacks proper
    numbering.xml definitions, which silently breaks bullet/numbered
    list rendering (items appear as plain paragraphs with no bullet
    marker). Starting from pandoc's default and only touching the font
    preserves its working list styles while still fixing the Vietnamese
    diacritic issue (Word's default theme font has incomplete glyph
    coverage for some Vietnamese characters).
    """
    global _REFERENCE_DOCX_CACHE
    if _REFERENCE_DOCX_CACHE and _REFERENCE_DOCX_CACHE.exists():
        return _REFERENCE_DOCX_CACHE

    tmp_dir = Path(tempfile.gettempdir())
    pandoc_default = tmp_dir / "an_du_pandoc_default.docx"
    path = tmp_dir / "an_du_reference.docx"

    result = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get pandoc default reference doc: {result.stderr}")
    pandoc_default.write_bytes(result.stdout)

    doc = Document(str(pandoc_default))
    styles = doc.styles

    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(11)

    for style_name in ["Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"]:
        try:
            styles[style_name].font.name = "Arial"
        except KeyError:
            pass

    doc.save(path)
    _REFERENCE_DOCX_CACHE = path
    return path


def markdown_to_docx_base64(markdown_text: str) -> str:
    """
    Convert markdown report text to a .docx file via pandoc,
    return as base64 string ready to send over JSON.

    Apps Script usage (decode + save to Drive — runs as real user,
    so no service-account storage quota issue):

        var bytes = Utilities.base64Decode(result.docx_base64);
        var blob  = Utilities.newBlob(bytes, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'BC_' + token + '.docx');
        var file  = folder.createFile(blob);
    """
    with tempfile.TemporaryDirectory() as tmp:
        md_path   = Path(tmp) / "report.md"
        docx_path = Path(tmp) / "report.docx"
        md_path.write_text(markdown_text, encoding="utf-8")

        reference_doc = _get_reference_docx()

        result = subprocess.run(
            ["pandoc", "-f", "markdown+hard_line_breaks", str(md_path),
             "-o", str(docx_path), f"--reference-doc={reference_doc}"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"pandoc conversion failed: {result.stderr}")

        docx_bytes = docx_path.read_bytes()
        return base64.b64encode(docx_bytes).decode("utf-8")



def generate_report_stream(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Generator[str, None, None]:
    """
    True streaming version — yields each text chunk AS IT ARRIVES from
    Anthropic, so the HTTP response itself carries continuous bytes the
    whole time generation is running. This is what actually prevents an
    idle-connection gateway timeout (Railway or otherwise): the previous
    non-streaming-HTTP version called Anthropic with streaming internally
    but still sent ZERO bytes to the client until everything finished —
    which does nothing to keep an idle-timeout-based proxy from cutting
    the connection.

    Yields the report text progressively, then a final metadata block:

        <report text, streamed chunk by chunk>

        ===METADATA===
        {"model": ..., "input_tokens": ..., "output_tokens": ..., "estimated_cost_usd": ...}

    Does NOT include docx conversion — call /webhook/markdown-to-docx
    separately with the collected text if you need the .docx file.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key, timeout=900.0)
    prompt = build_prompt(student_info, scores)

    print(f"=== Starting streaming generation for {student_info.get('name', '')} "
          f"(prompt length: {len(prompt)} chars) ===")

    full_text_parts = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text_parts.append(chunk)
            yield chunk  # real bytes flow to the HTTP client immediately
        final_message = stream.get_final_message()

    text = "".join(full_text_parts)
    input_tokens  = final_message.usage.input_tokens
    output_tokens = final_message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 5) + (output_tokens / 1_000_000 * 25)

    print(f"=== REPORT GENERATED — name={student_info.get('name', '')} "
          f"input_tokens={input_tokens} output_tokens={output_tokens} "
          f"cost_usd={round(cost, 4)} ===")
    print("=== REPORT TEXT START ===")
    print(text)
    print("=== REPORT TEXT END ===")

    metadata = {
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }
    yield "\n\n===METADATA===\n" + json.dumps(metadata, ensure_ascii=False)


def generate_report(student_info: Dict[str, Any], scores: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    # Explicit generous timeout (default client timeout can be too short
    # for long generations like this — Anthropic recommends streaming +
    # an explicit timeout for any request expected to run several minutes).
    client = anthropic.Anthropic(api_key=api_key, timeout=900.0)
    prompt = build_prompt(student_info, scores)

    print(f"=== Starting generation for {student_info.get('name', '')} "
          f"(prompt length: {len(prompt)} chars) ===")

    # Stream the response instead of a single synchronous create() call —
    # this is Anthropic's documented recommendation for long-running
    # generations (full SOP + Master Router can push this well past a
    # minute), and avoids edge cases where a long non-streaming call
    # gets dropped before the final response is assembled.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for _ in stream.text_stream:
            pass  # could log incremental progress here if needed
        final_message = stream.get_final_message()

    text = "".join(block.text for block in final_message.content if block.type == "text")

    input_tokens  = final_message.usage.input_tokens
    output_tokens = final_message.usage.output_tokens
    cost = (input_tokens / 1_000_000 * 5) + (output_tokens / 1_000_000 * 25)

    # Defensive logging — print the full result to stdout (visible in
    # Railway's log viewer) the moment generation succeeds, BEFORE any
    # downstream step (docx conversion, HTTP response transport) that
    # could fail or time out. Without this, a gateway timeout after a
    # successful (and billed) Anthropic call would lose the output
    # entirely with no way to recover it.
    print(f"=== REPORT GENERATED — token={student_info.get('name', '')} "
          f"input_tokens={input_tokens} output_tokens={output_tokens} "
          f"cost_usd={round(cost, 4)} ===")
    print("=== REPORT TEXT START ===")
    print(text)
    print("=== REPORT TEXT END ===")

    try:
        docx_base64 = markdown_to_docx_base64(text)
    except Exception as e:
        docx_base64 = None  # don't fail the whole request if pandoc has an issue
        print(f"WARNING: docx conversion failed: {e}")

    return {
        "report_text": text,
        "docx_base64": docx_base64,
        "model": MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
    }
