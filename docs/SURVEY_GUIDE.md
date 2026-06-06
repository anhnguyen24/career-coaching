# Hướng Dẫn Tạo Bộ Câu Hỏi Mới

Tài liệu này dành cho người soạn bộ câu hỏi hướng nghiệp.
Khi có bộ câu hỏi mới, dùng prompt bên dưới để nhờ AI chuyển sang file JSON đúng chuẩn.

---

## Quy Trình

```
1. Soạn xong 180 câu hỏi và hướng dẫn chấm điểm
        ↓
2. Dùng prompt bên dưới với AI assistant
        ↓
3. AI trả về file JSON
        ↓
4. Kiểm tra JSON (xem checklist bên dưới)
        ↓
5. Gửi file JSON cho dev để deploy
```

---

## Checklist Kiểm Tra Trước Khi Gửi

Sau khi AI tạo xong JSON, kiểm tra các mục sau:

- [ ] Đúng 180 câu (MBTI: 1–60, Holland: 61–120, OCEAN: 121–180)
- [ ] Đổi `"version"` thành version mới (ví dụ `"v3"`)
- [ ] Câu có đánh dấu [R] → `"reversed": true`, còn lại → `"reversed": false`
- [ ] Các câu `reversed: true` phải xuất hiện trong mảng `"reversed"` của scoring group
- [ ] Tổng weight trong SSS (hoặc composite score khác) bằng 1.0
- [ ] Không có chữ giải thích, không có ``` trong output — chỉ JSON thuần túy

---

## Prompt Cho AI

Sao chép toàn bộ đoạn dưới đây, dán vào AI assistant, điền phần còn thiếu:

---

```
Bạn là trợ lý chuyên chuyển đổi bộ câu hỏi hướng nghiệp sang định dạng JSON.

Nhiệm vụ: Chuyển toàn bộ 180 câu hỏi và cấu hình chấm điểm sang file JSON
theo đúng cấu trúc của file mẫu dưới đây.

FILE MẪU (làm theo y hệt cấu trúc này, chỉ thay nội dung câu hỏi và scoring):
===BEGIN TEMPLATE===
{
  "version": "v2",
  "metadata": {
    "name": "Bộ Khảo Sát Hướng Nghiệp GenZ",
    "total_questions": 180,
    "scale": {
      "min": 1,
      "max": 5,
      "reverse_formula": "6 - score"
    },
    "notes": "v2 — all 3 tests use Likert 1-5. MBTI uses average, Holland uses sum, OCEAN uses average with reverse scoring."
  },
  "tests": [
    {
      "id": "mbti",
      "name": "Test 1 — MBTI",
      "question_range": { "start": 1, "end": 60 },
      "questions": [
        { "number": 1, "axis": "E", "reversed": false, "text": "Đi đâu đông vui là em dễ lên mood thật.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 2, "axis": "E", "reversed": false, "text": "Gặp người lạ, em thường bắt chuyện khá nhanh.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 3, "axis": "E", "reversed": false, "text": "Trong nhóm, em hay là người mở lời trước.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 4, "axis": "E", "reversed": false, "text": "Chỗ nào càng rôm rả, em càng dễ nhập cuộc.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 5, "axis": "E", "reversed": false, "text": "Em hay nói ra rồi mới thấy rõ mình đang nghĩ gì.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 6, "axis": "E", "reversed": false, "text": "Làm việc có người qua lại, tương tác nhiều thường làm em có năng lượng hơn.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 7, "axis": "I", "reversed": false, "text": "Đi chơi hay giao tiếp nhiều xong, em cần ở riêng một lúc để hồi pin.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 8, "axis": "I", "reversed": false, "text": "Em thường nghĩ trong đầu khá lâu rồi mới nói ra.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 9, "axis": "I", "reversed": false, "text": "Em thích nói chuyện ít người nhưng nói cho sâu hơn là nói đông cho vui.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 10, "axis": "I", "reversed": false, "text": "Nếu bị kéo đi social liên tục, em khá dễ mệt.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 11, "axis": "I", "reversed": false, "text": "Gặp người mới, em thường cần warm-up chứ không bung liền.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" },
        { "number": 12, "axis": "I", "reversed": false, "text": "Em thích có khoảng riêng của mình hơn là lúc nào cũng phải hòa vào đám đông.", "low_label": "Rất không đúng với mình", "high_label": "Rất đúng với mình" }
        ... (tiếp tục đến câu 60 theo cùng format)
      ]
    },
    {
      "id": "holland",
      "name": "Test 2 — Holland / RIASEC",
      "question_range": { "start": 61, "end": 120 },
      "questions": [
        { "number": 61, "axis": "R", "reversed": false, "text": "...", "low_label": "Không giống mình", "high_label": "Rất giống mình" }
        ... (tiếp tục đến câu 120)
      ]
    },
    {
      "id": "ocean",
      "name": "Test 3 — OCEAN / Big Five",
      "question_range": { "start": 121, "end": 180 },
      "questions": [
        { "number": 121, "axis": "O", "reversed": false, "text": "...", "low_label": "Không giống mình", "high_label": "Rất giống mình" },
        { "number": 131, "axis": "O", "reversed": true, "text": "...", "low_label": "Không giống mình", "high_label": "Rất giống mình" }
        ... (tiếp tục đến câu 180, reversed: true cho câu đảo chiều)
      ]
    }
  ],
  "scoring": {
    "tests": [
      {
        "test_id": "mbti",
        "method": "average",
        "clarity_thresholds": [
          { "max": 0.20, "label": "Rất lưng chừng" },
          { "max": 0.40, "label": "Nghiêng nhẹ" },
          { "max": 0.70, "label": "Nghiêng vừa" },
          { "max": null, "label": "Khá rõ" }
        ],
        "overall_clarity_thresholds": [
          { "max": 0.20, "label": "Rất lưng chừng" },
          { "max": 0.40, "label": "Nghiêng nhẹ" },
          { "max": 0.70, "label": "Nghiêng vừa" },
          { "max": null, "label": "Khá rõ" }
        ],
        "groups": [
          { "id": "E", "name": "Hướng ngoại", "forward": [1,2,3,4,5,6], "reversed": [], "paired_with": "I" },
          { "id": "I", "name": "Hướng nội", "forward": [7,8,9,10,11,12], "reversed": [], "paired_with": "E" },
          { "id": "S", "name": "Thực tế", "forward": [13,14,15,16,17,18,19,20,21,22,23,24], "reversed": [], "paired_with": "N" },
          { "id": "N", "name": "Trực giác", "forward": [25,26,27,28,29,30,31,32,33,34,35,36], "reversed": [], "paired_with": "S" },
          { "id": "T", "name": "Lý trí", "forward": [37,38,39,40,41,42], "reversed": [], "paired_with": "F" },
          { "id": "F", "name": "Cảm xúc", "forward": [43,44,45,46,47,48], "reversed": [], "paired_with": "T" },
          { "id": "J", "name": "Nguyên tắc", "forward": [49,50,51,52,53,54], "reversed": [], "paired_with": "P" },
          { "id": "P", "name": "Linh hoạt", "forward": [55,56,57,58,59,60], "reversed": [], "paired_with": "J" }
        ]
      },
      {
        "test_id": "holland",
        "method": "sum",
        "max_per_group": 50,
        "groups": [
          { "id": "R", "name": "Thực tế / Kỹ thuật", "forward": [61,62,63,64,65,66,67,68,69,70], "reversed": [] },
          { "id": "I", "name": "Nghiên cứu / Tư duy", "forward": [71,72,73,74,75,76,77,78,79,80], "reversed": [] },
          { "id": "A", "name": "Nghệ thuật / Sáng tạo", "forward": [81,82,83,84,85,86,87,88,89,90], "reversed": [] },
          { "id": "S", "name": "Xã hội / Hỗ trợ", "forward": [91,92,93,94,95,96,97,98,99,100], "reversed": [] },
          { "id": "E", "name": "Doanh nghiệp / Lãnh đạo", "forward": [101,102,103,104,105,106,107,108,109,110], "reversed": [] },
          { "id": "C", "name": "Quản lý / Tổ chức", "forward": [111,112,113,114,115,116,117,118,119,120], "reversed": [] }
        ]
      },
      {
        "test_id": "ocean",
        "method": "average_with_reverse",
        "interpretation_thresholds": [
          { "max": 1.80, "label": "Thấp rõ" },
          { "max": 2.40, "label": "Vừa thấp" },
          { "max": 3.20, "label": "Trung bình" },
          { "max": 3.80, "label": "Vừa cao" },
          { "max": null, "label": "Cao" }
        ],
        "groups": [
          { "id": "O", "name": "Cởi mở / Sáng tạo", "forward": [121,122,123,124,125,126,127,128,129,130], "reversed": [131,132] },
          { "id": "C", "name": "Cẩn thận / Kỷ luật", "forward": [133,134,135,136,137,138,139,140], "reversed": [141,142,143,144] },
          { "id": "E", "name": "Hướng ngoại", "forward": [145,146,147,148,149,150,151,152], "reversed": [153,154,155,156] },
          { "id": "A", "name": "Dễ chịu / Hợp tác", "forward": [157,158,159,160,161,162,163,164], "reversed": [165,166,167,168] },
          { "id": "N", "name": "Nhạy cảm / Lo lắng", "forward": [169,170,171,172,173,174,175,176], "reversed": [177,178,179,180] }
        ]
      }
    ],
    "composite_scores": [
      {
        "id": "sss",
        "name": "Social Synchronization Score",
        "label": "SSS",
        "components": [
          {
            "source": "bipolar_ratio",
            "weight": 0.30,
            "test_id": "mbti",
            "ratio_formula": {
              "numerator_group": "E",
              "denominator_groups": ["E", "I"],
              "scale_min": 1,
              "scale_max": 5,
              "formula": "1 + 4 * (MBTI_E / (MBTI_E + MBTI_I))"
            }
          },
          {
            "source": "test_group",
            "weight": 0.40,
            "test_id": "ocean",
            "group_id": "E"
          },
          {
            "source": "question_subset",
            "weight": 0.30,
            "forward": [145, 148, 149, 150, 152],
            "reversed": [154, 155, 156]
          }
        ],
        "interpretation_thresholds": [
          { "max": 1.80, "label": "Thấp rõ" },
          { "max": 2.40, "label": "Vừa thấp" },
          { "max": 3.20, "label": "Trung bình" },
          { "max": 3.80, "label": "Vừa cao" },
          { "max": null, "label": "Cao" }
        ]
      }
    ]
  }
}
===END TEMPLATE===

QUY TẮC BẮT BUỘC:
1. Tổng số câu phải đúng 180 (MBTI: câu 1-60, Holland: câu 61-120, OCEAN: câu 121-180)
2. Mỗi câu phải có đủ 6 trường: number, axis, reversed, text, low_label, high_label
3. Câu có đánh dấu [R] hoặc đảo chiều thì reversed = true, còn lại reversed = false
4. Câu reversed = true phải xuất hiện trong mảng "reversed" của scoring group tương ứng
5. "tests" là một mảng — giữ nguyên 3 phần tử theo thứ tự: mbti, holland, ocean
6. "scoring.tests" là một mảng — giữ nguyên thứ tự và cấu trúc của từng test
7. Holland dùng method = "sum", MBTI dùng "average", OCEAN dùng "average_with_reverse"
8. Tổng weight trong mỗi composite score phải bằng 1.0
9. Điền version mới vào field "version" (ví dụ "v3")
10. Không thêm bất kỳ field nào không có trong template
11. Output chỉ là JSON thuần túy — không có giải thích, không có markdown, không có ```json

BỘ CÂU HỎI VÀ CHẤM ĐIỂM MỚI:
[DÁN TOÀN BỘ 180 CÂU VÀ HƯỚNG DẪN CHẤM ĐIỂM VÀO ĐÂY]
```

---

## Lưu Ý Khi Chấm Điểm Thay Đổi

Nếu muốn thay đổi cách chấm điểm (ví dụ: thêm trục mới, đổi câu hỏi vào nhóm khác, thay đổi thang điểm SSS), hãy mô tả rõ trong phần "BỘ CÂU HỎI VÀ CHẤM ĐIỂM MỚI" và nhờ AI cập nhật phần `scoring` tương ứng.

Ví dụ:
- "Thêm trục X vào MBTI với câu 61-66 (nhưng phải dời Holland sang câu 67-126)"
- "Đổi weight SSS: MBTI 40%, OCEAN_E 30%, Raw Social 30%"
- "Thêm composite score mới tên CCS gồm OCEAN_O (50%) và Holland_A (50%)"