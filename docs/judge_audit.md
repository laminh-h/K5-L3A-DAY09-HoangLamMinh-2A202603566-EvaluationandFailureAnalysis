# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY: verdict của judge lưu sẵn trong CSV, không gọi model). Lớp dương là **FAIL** vì việc của judge là *tìm* lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** | **dùng** (chỉ cho tone, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ và R dưới sàn) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (FAIL = dương):

| | tp | fp | fn | tn | Tỉ lệ FAIL judge thấy | Sau Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 | 0.30 (sens 0.8, spec 66/70 = 0.943) |
| helpful | 9 | 0 | 21 | 70 | 0.09 | 0.30 (sens 0.3, spec 1.0) |

Output gốc:
```
$ python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
n=100 P=0.857 R=0.8 kappa=0.757 {'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}
fail rate observed 0.28 -> corrected 0.3
PASS floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}
$ python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
n=100 P=1.0 R=0.3 kappa=0.375 {'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}
fail rate observed 0.09 -> corrected 0.3
FAIL floors {'kappa': 0.6, 'precision': 0.8, 'recall': 0.7}
```

## ≥5 case audit thủ công
Đủ 10 bất đồng của `tone_ok` và 3 nhóm bất đồng đại diện cho cả 21 bất đồng của `helpful`.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Judge coi suồng sã là thân thiện. Rubric: *xưng "em/bạn", tiểu từ "nha/nhé" với khách đang khiếu nại → FAIL*; thêm ví dụ âm tính này vào few-shot. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ… rồi nha." | PASS | FAIL | **Người** | Cùng lỗi như #1 (xưng "bạn"). Gộp vào một quy tắc xưng hô: chỉ dùng "anh/chị", "quý khách". |
| 3 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ bắt từ lịch sự bề mặt ("Dạ, vui lòng"). Rubric: *câu mệnh lệnh / chặn khách liên hệ → FAIL dù có kính ngữ*. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric: *xin lỗi không bắt buộc khi yêu cầu đã giải quyết; ngắn gọn, đủ ý = PASS*. |
| 5 | tone H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | CS LogiX cho phép từ "refund". Rubric: thêm danh sách thuật ngữ được phép (refund, ship, COD). |
| 6 | tone H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Lỗi thật là **hứa ngoài kết quả hệ thống**, không phải giọng điệu. Hành động: đưa khỏi phạm vi tone; số tiền / cam kết chấm bằng code (`reply_matches_ledger`, FM-08). Rubric tone ghi rõ: "không chấm nội dung tiền". |
| 7 | tone H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric: *emoji cười trong ngữ cảnh khiếu nại → FAIL*. |
| 8 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn… ạ." | FAIL | PASS | **Judge** | Ghi chú gốc: người đọc nhầm ticket. Hành động: **sửa nhãn người** ở phiên bản CSV kế tiếp (không sửa file public đang dùng để chấm). Sửa xong thì tp 25 / fp 3, P ≈ 0.893. |
| 9 | tone H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | **Người** (lỗi nhỏ) | Lặp "Dạ" là lỗi gõ, không phải giọng điệu thô. Rubric: *lỗi chính tả/lặp từ không làm FAIL tone*; nếu cần, đo bằng một check chính tả riêng. |
| 10 | tone H-094 "Da, LogiX da hoan 40.000đ…" (mất dấu) | PASS | FAIL | **Người** | Rubric: *mất dấu tiếng Việt / dịch máy → FAIL*. Có thể thay bằng check code (tỉ lệ ký tự có dấu). |
| 11 | helpful HL-015, HL-020, HL-062, HL-087, HL-100: reply ngắn, nêu số tiền **khác ledger** (vd. 55.000đ, ledger ghi 40.000đ) | PASS | FAIL | **Người** | Judge **không có ledger** trong input nên không thể biết số sai. Đây chính là FM-08. Hành động: không dùng judge; chấm bằng code `ReplyMatchesLedger`. |
| 12 | helpful HL-016, HL-028, HL-035, HL-041, HL-043, HL-053, HL-058, HL-070, HL-072, HL-074, HL-090, HL-096, HL-098: reply dài, xin lỗi lặp lại, số tiền sai | PASS | FAIL | **Người** | Thiên vị độ dài / xin lỗi (verbosity bias): 13/21 bất đồng là reply "đệm" lời xin lỗi. Rubric helpful: *phải nêu đúng kết quả; lời xin lỗi lặp không cộng điểm*. |
| 13 | helpful HL-047, HL-091, HL-097 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Không nói kết quả (hoàn bao nhiêu / từ chối vì sao). Rubric: *reply phải nêu trạng thái và số tiền cụ thể*. |

## Kết luận
- **`tone_ok` dùng được** (κ 0.757, P 0.857, R 0.8 đều trên sàn), nhưng chỉ cho giọng điệu; nó không được quyết định gì về tiền. 6/10 bất đồng là judge bỏ sót (fn), nên tỉ lệ lỗi thật sau hiệu chỉnh Rogan-Gladen là 0.30 so với 0.28 judge thấy.
- **`helpful` bị loại.** Ma trận `tp 9, fp 0, fn 21, tn 70`: precision 1.0 trông đẹp nhưng recall chỉ 0.30. Judge bỏ sót 21/30 reply hỏng, nhiều nhất là reply nói sai số tiền so với ledger (18/21) và reply đệm lời xin lỗi. κ = 0.375 < 0.6. Gate dựa trên judge này sẽ báo tỉ lệ lỗi 9% trong khi thực tế là 30% (Rogan-Gladen), tức cho qua cả những PR làm hỏng câu trả lời. Phần "helpful" quan trọng nhất (đúng số tiền) chuyển sang grader code `reply_matches_ledger` (blocking, FM-08). Phần còn lại ("có nêu kết quả cụ thể không") chỉ dùng lại khi rubric đã sửa như trên và judge được calibrate lại đạt FLOORS.
- **Quy tắc giữ nguyên:** tiền và approval luôn chấm bằng code; judge chỉ cho tiêu chí đã qua calibration.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí, chưa có tập held-out). Rubric sửa xong có thể overfit vào chính các case này. Cần nhãn người mới (≥100 reply từ trace thật, 2 người gán, đo κ giữa người với người) trước khi tin vào κ của judge.
