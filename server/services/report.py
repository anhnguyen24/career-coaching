"""
server/services/report.py — AI career report generation

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
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import anthropic
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

MODEL      = "claude-opus-4-7"
MAX_TOKENS = 32000
# NOTE: raised from 20000 after the first real V4.2 test (Hà Quyên,
# 2026-07-13) hit exactly 20000 output tokens and got cut off mid-
# sentence in the final [AUDIT NỘI BỘ] section — the V4.2 SOP's
# required structure (15 numbered sections, per-ngành deep-dives x5,
# O*NET + VSCO tables, full roadmap, Quest section, audit appendix) is
# simply longer than the older report format this was tuned for.
# Claude Opus 4.7 supports up to 128,000 output tokens on the standard
# Messages API (per Anthropic's docs) — 20000 was using under a fifth
# of that. 32000 gives real headroom (that test was maybe a few
# hundred tokens short of finishing) without the much larger worst-
# case cost of maxing out at 128K ($25/million output tokens — 128K
# alone could run ~$3.20 if ever fully used; 32K keeps worst case
# closer to ~$0.80 for output).

PROMPTS_DIRNAME = "prompts"
SOP_FILENAME           = "quy_trinh_chot_case_v4_2.md"
MASTER_ROUTER_FILENAME  = "master_router_prompt_v4_2.md"
TRONG_NUOC_FILENAME     = "prompt_2_5_trong_nuoc_v4_2.md"

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


# ============================================================
# Transcript file handling (Pass 2)
#
# Students can attach one or more transcript files (PDF or image) in
# the main survey. Apps Script fetches these from Drive, base64-
# encodes them, and sends them as transcript_files in the
# generate-report-async payload — see mirror_check_response_trigger.gs.
# Claude reads them directly as real document/image content (not OCR'd
# separately), via Anthropic's native document/image content blocks.
# ============================================================

# Anthropic's Messages API uses a different content-block "type" for
# PDFs ("document") vs. images ("image") — this maps each accepted
# mime type to the correct block type. Anything not in this dict is
# rejected (logged, not sent to Claude) rather than guessed at.
TRANSCRIPT_MIME_TO_BLOCK_TYPE = {
    "application/pdf": "document",
    "image/jpeg": "image",
    "image/png": "image",
    "image/gif": "image",
    "image/webp": "image",
}

TRANSCRIPT_MAX_FILES = 5
# ~20MB of actual file bytes, expressed as a base64-character-count
# limit (base64 inflates size by ~4/3) — a generous cap for scanned
# transcripts/report cards, well above what real report-card photos
# or a multi-page PDF should ever need.
TRANSCRIPT_MAX_TOTAL_BASE64_CHARS = 20 * 1024 * 1024 * 4 // 3


def _build_transcript_content_blocks(transcript_files: Optional[list]) -> list:
    """
    Convert the raw transcript_files list (from the API request — each
    item a dict with filename/mime_type/data) into Anthropic API
    content blocks, ready to prepend to the text prompt.

    Applies the same kind of defensive validation as everywhere else
    in this pipeline: unsupported mime types are skipped (not sent to
    Claude, not a hard failure), and both a file-count cap and a
    total-size cap protect against one oversized/malformed upload
    silently blowing up the request. Any single bad file is skipped
    with a log line rather than failing the whole report — a report
    generated from *some* of the transcript is better than no report
    at all.
    """
    if not transcript_files:
        return []

    blocks = []
    total_base64_chars = 0
    files_included = 0

    for f in transcript_files:
        filename = f.get("filename", "unknown")
        mime_type = f.get("mime_type", "")
        data = f.get("data", "")

        if files_included >= TRANSCRIPT_MAX_FILES:
            print(f"WARNING: Transcript file '{filename}' skipped — already at "
                  f"TRANSCRIPT_MAX_FILES ({TRANSCRIPT_MAX_FILES}) limit.")
            continue

        if mime_type not in TRANSCRIPT_MIME_TO_BLOCK_TYPE:
            print(f"WARNING: Transcript file '{filename}' skipped — unsupported "
                  f"mime type '{mime_type}'. Allowed: {list(TRANSCRIPT_MIME_TO_BLOCK_TYPE.keys())}")
            continue

        if not data:
            print(f"WARNING: Transcript file '{filename}' skipped — no data.")
            continue

        if total_base64_chars + len(data) > TRANSCRIPT_MAX_TOTAL_BASE64_CHARS:
            print(f"WARNING: Transcript file '{filename}' skipped — would exceed "
                  f"total transcript size cap ({TRANSCRIPT_MAX_TOTAL_BASE64_CHARS} base64 chars).")
            continue

        block_type = TRANSCRIPT_MIME_TO_BLOCK_TYPE[mime_type]
        blocks.append({
            "type": block_type,
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": data,
            },
        })
        total_base64_chars += len(data)
        files_included += 1

    if blocks:
        print(f"=== Attached {len(blocks)} transcript file(s) as document/image content "
              f"({total_base64_chars} base64 chars total) ===")

    return blocks


def _build_mirror_check_block(mirror_check: Optional[Dict[str, Any]]) -> str:
    """
    Build the "Mirror Check response" input block required by the
    updated (V4.2) Master Router / Siêu Prompt 2.5 prompts. Per those
    documents, this block must contain:
      - Micro-portrait app đề xuất mạnh nhất (score_matched)
      - Học sinh chọn micro-portrait nào (student_choice)
      - Câu học sinh tick/highlight là đúng nhất
      - Câu học sinh phản hồi không giống mình nếu có
      - Mirror Fit sơ bộ (color / level)

    If mirror_check is None (student hasn't completed Mirror Check yet,
    or this is a legacy /test-report call made before Mirror Check
    existed), returns the explicit fallback line the V4.2 SOP requires:
    the report must say self-confirmation data is missing and treat the
    result as an opening map needing Quest-verification, rather than
    silently omitting the section.
    """
    if not mirror_check:
        return (
            "Mirror Check response: Chưa có dữ liệu self-confirmation; "
            "kết quả cần đọc như bản đồ mở đầu và cần Quest để xác nhận."
        )

    score_matched   = mirror_check.get("score_matched") or "Không rõ"
    student_choice  = mirror_check.get("student_choice") or "Không rõ"
    highlight       = mirror_check.get("highlight_answer") or "Không có"
    mismatch        = mirror_check.get("mismatch_answer") or "Không có"
    fit_color       = mirror_check.get("mirror_fit_color") or ""
    fit_level       = mirror_check.get("mirror_fit_level") or ""
    fit_combined    = f"{fit_color} / {fit_level}" if fit_color or fit_level else "Không rõ"

    return f"""Mirror Check response:
- Micro-portrait app đề xuất mạnh nhất: {score_matched}
- Học sinh chọn micro-portrait nào: {student_choice}
- Câu học sinh tick/highlight là đúng nhất: {highlight}
- Câu học sinh phản hồi không giống mình nếu có: {mismatch}
- Mirror Fit sơ bộ: {fit_combined}"""


def build_prompt(
    student_info: Dict[str, Any],
    scores: Dict[str, Any],
    mirror_check: Optional[Dict[str, Any]] = None,
    has_transcript_files: bool = False,
) -> str:
    sop           = _read_file(SOP_FILENAME)
    master_router = _read_file(MASTER_ROUTER_FILENAME)

    route = _detect_route(student_info.get("direction", ""))

    extra_branch_doc = ""
    if route == "B":
        extra_branch_doc = "\n\n---\n\n# TÀI LIỆU BỔ SUNG — SIÊU PROMPT 2.5 (TRONG NƯỚC)\n\n" + _read_file(TRONG_NUOC_FILENAME)

    # Two independent ways transcript info can arrive:
    #   1. has_transcript_files=True — actual file(s) (PDF/image) are attached
    #      as separate document/image content blocks in the API call itself
    #      (see _build_transcript_content_blocks) — Claude reads them
    #      directly, this is just a text pointer telling it they're there.
    #   2. student_info["transcript"] — a plain text description (legacy
    #      fallback, used if no real files were ever wired in for this call).
    # Both can't really apply at once in practice, but handle gracefully
    # either way rather than assuming only one path is ever used.
    if has_transcript_files:
        transcript_line = (
            "\nHọc bạ (bằng chứng minh họa, không tự chốt hướng): đã đính kèm bên dưới "
            "dưới dạng file/ảnh — đọc trực tiếp nội dung file để lấy thông tin điểm số, "
            "môn mạnh/môn yếu. Không bịa thêm nếu file khó đọc; nếu vậy, ghi rõ trong "
            "phần audit rằng cần xác nhận lại thủ công."
        )
    else:
        transcript = student_info.get("transcript")
        transcript_line = f"\nHọc bạ (bằng chứng minh họa, không tự chốt hướng): {transcript}" if transcript else ""

    mirror_check_block = _build_mirror_check_block(mirror_check)

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

{mirror_check_block}

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

Trước khi viết bất kỳ kết luận ngành/major nào, PHẢI đi qua MIRROR CHECK GATE (6 câu hỏi bắt
buộc) theo đúng yêu cầu trong SIÊU PROMPT 3.0 MASTER ROUTER, dùng dữ liệu Mirror Check response
ở trên. Nếu Mirror Fit là Cam hoặc Đỏ, không được viết ngành/major theo giọng chốt cứng —
phải nêu rõ vùng cần Quest kiểm chứng trước khi khẳng định.

YÊU CẦU BẮT BUỘC VỀ CẤU TRÚC ĐẦU RA (áp dụng thêm, ngoài quy trình ở trên):

1. **KHÔNG in 4 chữ MBTI (ví dụ "ENTP") ở bất kỳ đâu trong báo cáo.** Đây là tài liệu gửi
   thẳng cho gia đình — không có phần nội bộ riêng nữa (xem quy tắc 10). Chỉ tả tính cách
   bằng ngôn ngữ thường ("em có xu hướng...", "em hợp kiểu..."), không gắn nhãn 4 chữ cái ở
   bất kỳ đâu trong toàn bộ output.

2. **Xếp hạng major family/vùng nghề ưu tiên #1 phải tương ứng với mã Holland điểm cao nhất**
   trong Top 3, trừ khi có lý do rõ từ OCEAN/SSS/bối cảnh để hạ xuống — nếu đảo thứ tự, phải
   nêu lý do cụ thể ngay trong đoạn phân tích Holland (mục 4), không có phần audit riêng để
   đẩy lý do đó sang.

3. **Tên đọc riêng phải LÀ chính tiêu đề đó, không phải placeholder.** Viết heading là chính
   cụm từ đã nghĩ ra (ví dụ heading `### Người vẽ ý tưởng có phanh`), TUYỆT ĐỐI không viết
   heading kiểu `### [TÊN ĐỌC RIÊNG]` rồi mới ghi tên thật ở dòng dưới. Cụm từ ngắn (4-6 chữ),
   giàu hình ảnh, tóm gọn cách học sinh tạo giá trị (không phải tên nghề, không phải nhãn tính
   cách). Sau tên, viết 2-3 câu giải thích, làm rõ tên này không ép học sinh vào một nghề
   cố định.

4. **Mỗi major family/vùng nghề đề xuất phải được đào sâu đầy đủ**, không chỉ liệt kê tên:
   - Vì sao hợp (nối tới Holland/OCEAN/SSS/bối cảnh cụ thể của học sinh này)
   - Ngành này học gì (course content thực tế, không bịa tên trường cụ thể)
   - Việc thường gặp sau khi ra trường (5-8 việc cụ thể)
   - Vai trò nghề có thể hướng tới (3-5 chức danh cụ thể)
   - Mức ưu tiên (Rất cao / Cao / Khá cao / Có điều kiện / Trung bình) kèm lý do ngắn — viết
     dòng này dạng `**Mức ưu tiên:** Rất cao — <lý do>` bằng CHỮ THUẦN, không thêm bất kỳ
     emoji/icon/ký hiệu trang trí nào (không ⭐, không 🎯, không bất kỳ ký tự Unicode
     trang trí nào) trước hoặc sau.

5. **Phải có "Application Story Themes"** trong phần đầy đủ — 3-4 trục câu chuyện cho personal
   statement, mỗi trục 2-3 câu, gắn cụ thể vào dữ liệu/bối cảnh thật của học sinh này (không
   viết chung chung kiểu "em rất thích giúp người").

6. **Phải có "Hồ sơ nên có"** trong phần đầy đủ — personal statement nên xoay quanh chủ đề gì,
   loại portfolio/hoạt động nên có, loại project nên làm, hướng thư giới thiệu nên nhấn vào
   điều gì.

7. **Phải có mục "Lời kết gửi phụ huynh"** ở cuối — heading viết thường, KHÔNG có dấu ngoặc
   vuông bao quanh (viết `## Lời kết gửi phụ huynh`, không viết `## [LỜI KẾT GỬI PHỤ HUYNH]`).
   Đoạn ngắn (4-6 câu) tóm gọn tinh thần báo cáo: đây là bản đồ mở không phải bản án; nhấn lại
   điểm mạnh cốt lõi; nhắc gia đình tránh đẩy con theo hướng ngược với dữ liệu.

8. **Phải có mục "Mirror Check / Self-confirmation"** trong phần phân tích chi tiết, nêu rõ:
   Mirror Fit, vùng lệch nếu có, ảnh hưởng đến độ tin cậy của report, và Quest theo dõi
   tương ứng. Đây là báo cáo family-facing duy nhất — không có báo cáo nội bộ riêng để tách
   thông tin này ra, nên phải viết đủ chi tiết ngay tại đây bằng giọng phù hợp để phụ huynh
   đọc được (không dùng thuật ngữ kỹ thuật khô như "Mirror Mismatch Risk" trần trụi — diễn
   giải bằng câu bình thường).

9. **TUYỆT ĐỐI KHÔNG dùng emoji hoặc icon Unicode trang trí ở BẤT KỲ ĐÂU** trong toàn bộ
   output — không trong heading, không trong bullet, không ở đầu/cuối câu. Chỉ dùng chữ và
   dấu câu thông thường. Nhấn mạnh bằng **bold** hoặc *italic*, không dùng ký hiệu trang trí.

10. **KHÔNG tạo mục "PHẦN C – CONSULTANT NOTE" hay bất kỳ phần audit/nội bộ nào ở cuối báo
    cáo.** Toàn bộ output chỉ có 2 phần lớn — không có phần thứ ba. Mọi thông tin (Holland,
    OCEAN, Career Card, META64, O*NET, VSCO, Mirror Check, cảnh báo) đều viết trực tiếp trong
    2 phần đó, bằng giọng phù hợp để gia đình đọc trực tiếp — không có nơi nào để "giấu" nội
    dung kỹ thuật ra sau một bức tường ngăn cách nữa.

11. **Đặt tên 2 phần lớn bằng chữ cái, KHÔNG dùng từ "PHẦN".** Viết heading cấp 1 (H1) là
    `# A. <tiêu đề ngắn>` và `# B. <tiêu đề ngắn>` — ví dụ `# A. Bản đọc nhanh cho em Quyên`
    và `# B. Báo cáo đầy đủ cho phụ huynh`. KHÔNG viết "PHẦN A", "Phần A –", hay bất kỳ biến
    thể nào có chữ "Phần".

12. **Trong phần A, các mục con dùng chữ cái thường + dấu ngoặc đơn** (`a)`, `b)`, `c)`...)
    làm heading cấp 2 (H2), viết liền trước tiêu đề — ví dụ `## a) Em là kiểu người như thế
    nào`. Trong phần B, các mục lớn tiếp tục đánh số 1., 2., 3... như đã quy định ở các mục
    trên (giữ nguyên cách đánh số hiện tại của phần B, không đổi).

13. **Mỗi bảng markdown phải có một dòng caption in đậm ngay phía trên**, dạng
    `**Bảng N: <tên bảng>**`, với N là số thứ tự bảng tăng dần xuyên suốt toàn bộ báo cáo
    (không reset theo từng phần). Ví dụ: `**Bảng 1: O*NET Role Expansion**`.

14. **Chèn đúng 2 marker sau, mỗi marker trên một dòng riêng, không có gì khác trên dòng đó:**
    - Marker `[TOC]` — đặt ngay sau khối thông tin tiêu đề (Học sinh/Lớp/Route/Ngày phát
      hành) và TRƯỚC heading `# A. ...`. Đây sẽ được thay bằng mục lục thật.
    - Marker `[PAGEBREAK]` — đặt ngay TRƯỚC heading `# B. ...` (để phần B bắt đầu ở trang
      mới). KHÔNG đặt marker `[PAGEBREAK]` ở bất kỳ chỗ nào khác.
    Không giải thích hay nhắc đến 2 marker này trong nội dung — chúng chỉ là điểm đánh dấu kỹ
    thuật, sẽ được thay thế tự động, không hiển thị dạng chữ trong bản cuối.

15. **Trang đầu tiên (trước marker `[TOC]`) phải trình bày trang trọng, giống trang bìa**:
    tiêu đề báo cáo là `# BÁO CÁO HƯỚNG NGHIỆP CÁ NHÂN`, theo sau là khối thông tin học sinh
    (Học sinh / Lớp-Trường / Định hướng / Route case / Ngày phát hành) viết dạng
    `**Nhãn:** Giá trị` mỗi dòng — không thêm nội dung phân tích nào khác ở trang này.
"""

    return (
        "# TÀI LIỆU 1 — QUY TRÌNH CHỐT CASE\n\n" + sop +
        "\n\n---\n\n# TÀI LIỆU 2 — SIÊU PROMPT 3.0 MASTER ROUTER\n\n" + master_router +
        extra_branch_doc +
        "\n\n---\n\n# TÀI LIỆU 3 — DỮ LIỆU HỌC SINH VÀ NHIỆM VỤ\n\n" + filled_fields +
        "\n\n" + task
    )


_REFERENCE_DOCX_CACHE: Path | None = None


def _force_font_no_theme(style, font_name: str) -> None:
    """
    Set a style's font to a literal font name AND strip any theme font
    references (asciiTheme/hAnsiTheme/eastAsiaTheme/cstheme). Heading
    styles in Word templates (including pandoc's default reference doc)
    often carry ONLY a theme reference with no literal font at all —
    setting style.font.name alone adds a literal override but leaves
    the theme reference in place, and renderers can still follow the
    theme instead. Verified by inspecting the actual generated XML:
    without this, Heading styles kept asciiTheme="majorHAnsi" etc. and
    rendered in the theme's font (Calibri-like) instead of Arial.
    """
    style.font.name = font_name
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        return
    for theme_attr in ["asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"]:
        attr_qn = qn(f"w:{theme_attr}")
        if attr_qn in rFonts.attrib:
            del rFonts.attrib[attr_qn]
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    rFonts.set(qn("w:cs"), font_name)


def _get_reference_docx() -> Path:
    """
    Build (once, cached) a .docx with Arial set as the default font for
    Normal and Heading styles, used as pandoc's --reference-doc.

    Starts from pandoc's OWN default reference doc (via
    `pandoc --print-default-data-file reference.docx`), not a blank
    python-docx Document() — a blank document lacks proper numbering.xml
    definitions, which silently breaks bullet/numbered list rendering.
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

    # Iterate by name rather than dict-style lookup (doc.styles["Heading 1"]
    # raised KeyError on this specific template despite the style being
    # present when iterated — a latent-style quirk in pandoc's reference doc).
    target_names = {"Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"}
    for style in doc.styles:
        if style.name in target_names:
            _force_font_no_theme(style, "Arial")
            if style.name == "Normal":
                style.font.size = Pt(11)
                # Body text justified, not left-aligned — headings are left
                # untouched (they inherit their own alignment, which stays
                # left by default and should — justify only makes sense for
                # multi-line body paragraphs).
                style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    doc.save(path)
    _REFERENCE_DOCX_CACHE = path
    return path


_TOC_FIELD_OOXML = """```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
<w:sdt>
  <w:sdtPr>
    <w:docPartObj>
      <w:docPartGallery w:val="Table of Contents"/>
      <w:docPartUnique/>
    </w:docPartObj>
  </w:sdtPr>
  <w:sdtContent>
    <w:p>
      <w:pPr><w:pStyle w:val="TOCHeading"/></w:pPr>
      <w:r><w:t>Mục lục</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>
      <w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>(Nhấn phải chuột chọn "Update Field" hoặc phím F9 để cập nhật mục lục)</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
</w:sdtContent>
</w:sdt>
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```"""

_PAGEBREAK_OOXML = """```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```"""

# Matches common decorative Unicode emoji ranges — used as a backstop in
# case the model doesn't fully comply with the "no emoji" prompt rule.
# Deliberately does NOT strip ordinary Vietnamese diacritics or CJK
# characters, which live in entirely different Unicode blocks.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs, emoticons, transport, supplemental symbols
    "\U00002600-\U000027BF"  # misc symbols, dingbats (includes ⭐ U+2B50 is outside this — added below)
    "\U00002B00-\U00002BFF"  # misc symbols and arrows (covers ⭐ U+2B50)
    "\U0001F1E6-\U0001F1FF"  # regional indicator symbols (flags)
    "\U0000FE0F"             # variation selector-16 (emoji presentation)
    "]+",
    flags=re.UNICODE,
)


def _strip_trailing_consultant_section(text: str) -> str:
    """
    Safety net: the prompt now instructs the model to never generate a
    separate consultant/audit section (Phần C), but LLM instruction-
    following isn't 100% guaranteed — this truncates anything from a
    recognizable "Part C" heading onward if one slips through anyway,
    so a prompt-compliance miss can't leak internal-only content (MBTI
    codes, raw audit notes) into the family-facing document.
    """
    markers = [
        r"^#\s*C\.\s",
        r"PHẦN\s+C\b",
        r"CONSULTANT\s+NOTE",
        r"\[AUDIT\s+NỘI\s+BỘ\]",
    ]
    earliest_cut = None
    for pattern in markers:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match and (earliest_cut is None or match.start() < earliest_cut):
            earliest_cut = match.start()
    if earliest_cut is not None:
        print(f"WARNING: Trailing consultant/audit section detected and stripped "
              f"(model didn't fully follow the 'no Part C' instruction) — "
              f"cut at character {earliest_cut}")
        return text[:earliest_cut].rstrip()
    return text


def _replace_markers(text: str) -> str:
    """Replace the [TOC] and [PAGEBREAK] markers the prompt instructs the
    model to emit with their real raw-OOXML equivalents."""
    text = text.replace("[TOC]", _TOC_FIELD_OOXML)
    text = text.replace("[PAGEBREAK]", _PAGEBREAK_OOXML)
    return text


def _strip_stray_emoji(text: str) -> str:
    """Backstop for the 'no emoji' prompt rule — removes any that slip
    through despite the instruction, rather than relying on compliance
    alone."""
    return _EMOJI_PATTERN.sub("", text)


def _style_tables(docx_path: Path) -> None:
    """
    Post-process every table in the generated docx: add visible grid
    borders (pandoc's default table style renders borderless tables)
    and bold the header row. Done via python-docx after conversion
    rather than fighting pandoc's reference-doc table-style-name
    resolution, which is fragile and version-dependent.
    """
    doc = Document(str(docx_path))

    for table in doc.tables:
        tbl = table._tbl
        tblPr = tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "000000")
            borders.append(el)
        tblPr.append(borders)

        if table.rows:
            for cell in table.rows[0].cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.bold = True

    doc.save(str(docx_path))


def markdown_to_docx_base64(markdown_text: str) -> str:
    """
    Convert markdown report text to a .docx file via pandoc,
    return as base64 string ready to send over JSON.

    Pipeline:
      1. Strip any trailing consultant/audit section that slipped
         through despite the prompt instruction not to generate one.
      2. Replace [TOC] / [PAGEBREAK] markers with real raw-OOXML blocks
         (Word TOC field, page break) — see build_prompt()'s rule 14.
      3. Strip any stray emoji that slipped through despite the
         prompt's "no emoji" rule.
      4. Run pandoc (with raw_attribute enabled, required for the raw
         OOXML blocks above to pass through instead of being escaped).
      5. Post-process the resulting docx: add visible borders + bold
         header row to every table (pandoc's default is borderless).

    Apps Script usage (decode + save to Drive — runs as real user,
    so no service-account storage quota issue):

        var bytes = Utilities.base64Decode(result.docx_base64);
        var blob  = Utilities.newBlob(bytes, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'BC_' + token + '.docx');
        var file  = folder.createFile(blob);
    """
    markdown_text = _strip_trailing_consultant_section(markdown_text)
    markdown_text = _replace_markers(markdown_text)
    markdown_text = _strip_stray_emoji(markdown_text)

    with tempfile.TemporaryDirectory() as tmp:
        md_path   = Path(tmp) / "report.md"
        docx_path = Path(tmp) / "report.docx"
        md_path.write_text(markdown_text, encoding="utf-8")

        reference_doc = _get_reference_docx()

        result = subprocess.run(
            ["pandoc", "-f", "markdown+hard_line_breaks+raw_attribute", str(md_path),
             "-o", str(docx_path), f"--reference-doc={reference_doc}"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"pandoc conversion failed: {result.stderr}")

        _style_tables(docx_path)

        docx_bytes = docx_path.read_bytes()
        return base64.b64encode(docx_bytes).decode("utf-8")



def generate_report_stream(
    student_info: Dict[str, Any],
    scores: Dict[str, Any],
    mirror_check: Optional[Dict[str, Any]] = None,
) -> Generator[str, None, None]:
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
    prompt = build_prompt(student_info, scores, mirror_check)

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


def generate_report(
    student_info: Dict[str, Any],
    scores: Dict[str, Any],
    mirror_check: Optional[Dict[str, Any]] = None,
    transcript_files: Optional[list] = None,
) -> Dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    # Explicit generous timeout (default client timeout can be too short
    # for long generations like this — Anthropic recommends streaming +
    # an explicit timeout for any request expected to run several minutes).
    client = anthropic.Anthropic(api_key=api_key, timeout=900.0)

    transcript_blocks = _build_transcript_content_blocks(transcript_files)
    prompt = build_prompt(student_info, scores, mirror_check, has_transcript_files=bool(transcript_blocks))

    # Documents/images go BEFORE the text prompt in the content list —
    # this is Anthropic's documented ordering recommendation, so Claude
    # has the actual transcript content in view before reading the
    # instructions that reference it. Falls back to the old plain-string
    # form when there are no files, functionally identical to before.
    if transcript_blocks:
        message_content = transcript_blocks + [{"type": "text", "text": prompt}]
    else:
        message_content = prompt

    print(f"=== Starting generation for {student_info.get('name', '')} "
          f"(prompt length: {len(prompt)} chars, {len(transcript_blocks)} transcript file(s)) ===")

    # Stream the response instead of a single synchronous create() call —
    # this is Anthropic's documented recommendation for long-running
    # generations (full SOP + Master Router can push this well past a
    # minute), and avoids edge cases where a long non-streaming call
    # gets dropped before the final response is assembled.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": message_content}],
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


def _post_callback(callback_url: str, callback_secret: str, payload: Dict[str, Any]) -> None:
    """
    POST the finished (or failed) report result back to Apps Script's
    Web App callback URL. Uses stdlib urllib rather than requests/httpx
    to avoid adding a new dependency for a single outbound call.

    Failures here are logged, not raised — by the time this runs, the
    original HTTP request that kicked off generation is long since
    finished and has nothing to return an error to. If the callback
    itself fails (Apps Script down, wrong URL, etc.), the report is
    still fully generated and logged to stdout by generate_report()
    above — recoverable by hand from Railway logs if needed, just not
    automatically delivered to the doc.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        callback_url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Callback-Secret": callback_secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"=== Callback POST to {callback_url} returned HTTP {resp.status} ===")
    except urllib.error.HTTPError as e:
        print(f"ERROR: Callback POST to {callback_url} failed with HTTP {e.code}: {e.read()[:500]}")
    except Exception as e:
        print(f"ERROR: Callback POST to {callback_url} failed: {e}")


def _generate_report_and_callback(
    student_info: Dict[str, Any],
    scores: Dict[str, Any],
    mirror_check: Optional[Dict[str, Any]],
    transcript_files: Optional[list],
    token: str,
    callback_url: str,
    callback_secret: str,
) -> None:
    """
    Runs generate_report() to completion, then POSTs the result (or an
    error) back to callback_url. Meant to be run in a background thread
    — see generate_report_async() below — so the original HTTP request
    that triggered this can return immediately without waiting for the
    multi-minute generation to finish.
    """
    try:
        result = generate_report(student_info, scores, mirror_check, transcript_files)
        payload = {
            "token": token,
            "status": "done",
            "report_text": result["report_text"],
            "docx_base64": result["docx_base64"],
            "model": result["model"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "estimated_cost_usd": result["estimated_cost_usd"],
            # Echoed inside the body (not just the X-Callback-Secret header)
            # because Apps Script's doPost() cannot reliably read custom
            # request headers across all runtime versions — verifying
            # against a body field is more robust than relying on headers
            # actually surviving the trip.
            "callback_secret_echo": callback_secret,
        }
    except Exception as e:
        print(f"ERROR: Report generation failed for token {token}: {e}")
        payload = {
            "token": token,
            "status": "error",
            "error": str(e),
            "callback_secret_echo": callback_secret,
        }

    _post_callback(callback_url, callback_secret, payload)


def generate_report_async(
    student_info: Dict[str, Any],
    scores: Dict[str, Any],
    mirror_check: Optional[Dict[str, Any]],
    token: str,
    callback_url: str,
    callback_secret: str,
    transcript_files: Optional[list] = None,
) -> None:
    """
    Starts report generation in a background thread and returns
    immediately — does NOT wait for generation to finish. The caller
    (the /webhook/generate-report-async endpoint) should return a
    "started" response to its own caller right after calling this.

    When generation finishes (successfully or not), the result is
    POSTed to callback_url — see _generate_report_and_callback().
    """
    thread = threading.Thread(
        target=_generate_report_and_callback,
        args=(student_info, scores, mirror_check, transcript_files, token, callback_url, callback_secret),
        daemon=True,
    )
    thread.start()
