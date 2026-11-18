# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay từ CSV, FAIL là lớp dương tính).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng** (chỉ cho giọng văn, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại** |

Ma trận nhầm lẫn (output của script):
- tone_ok: `{'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}`. Tỉ lệ fail quan sát 0.28, sau hiệu chỉnh Rogan-Gladen là 0.30.
- helpful: `{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}`. Tỉ lệ fail quan sát 0.09, sau hiệu chỉnh Rogan-Gladen là 0.30.

## ≥5 case audit thủ công
Các case lấy từ những dòng judge và người bất đồng do `--audit` in ra. Cột "Ai đúng?" là đánh giá của mình sau khi đọc lại reply, và có dẫn cột `note` / `human_failure` của CSV.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em" và dùng "nha" là quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX" / "anh/chị"; cấm "em…nha", "bạn ơi"*, kèm 1 ví dụ FAIL. |
| 2 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ thấy "Dạ, vui lòng" mà bỏ qua giọng ra lệnh. Rubric thêm: *câu mệnh lệnh cấm khách liên hệ ("không cần nhắn thêm") = FAIL dù mở đầu lịch sự*. |
| 3 | tone H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | CSKH LogiX cho phép dùng "refund". Rubric thêm danh sách từ tiếng Anh được phép (refund, ship, voucher), để judge không phạt chỉ vì có tiếng Anh. |
| 4 | tone H-042 "đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi không bắt buộc khi yêu cầu đã được xử lý xong; ngắn gọn mà đủ ý = PASS*. |
| 5 | tone H-081 "đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | CSV ghi "nhãn người sai (đọc nhầm ticket)". Hành động: **sửa nhãn người** trong tập calibration, không sửa rubric. Đây là lý do κ không thể đạt 1 kể cả khi judge tốt. |
| 6 | tone H-063 "đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | **Người** | Reply hứa một kết quả ngoài hệ thống. Đây không hẳn là lỗi giọng văn mà là lỗi nội dung. Rubric tone thêm *cấm hứa hẹn ngoài kết quả hệ thống*, còn phần tiền vẫn do `reply_matches_ledger` (code) chấm. |
| 7 | tone H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Không rõ, nghiêng về **người** | Lặp "Dạ" do gõ nhầm. Lỗi nhỏ, không đáng đánh FAIL cả câu. Rubric: *lỗi gõ đơn lẻ không ảnh hưởng nghĩa = PASS*. |
| 8 | helpful HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000đ) | PASS | FAIL | **Người** | `human_failure` = "sai tiền". Judge đọc reply mà không đối chiếu ledger, nên không thể biết số tiền sai. Hành động: **bỏ tiêu chí số tiền khỏi judge helpful** và chuyển sang grader code `ReplyMatchesLedger` (FM-08). |
| 9 | helpful HL-016 / HL-028 (xin lỗi dài dòng + số tiền sai) | PASS | FAIL | **Người** | Judge bị lời xin lỗi trôi chảy đánh lừa. Hành động: giống #8. Rubric helpful chỉ giữ: đúng đơn, đúng trạng thái, có bước tiếp theo. |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | `human_failure` = "sai xưng hô", đây là lỗi thuộc tiêu chí tone, không phải helpful. Rubric: tách rõ hai tiêu chí; xưng hô do judge tone chấm. |

## Kết luận
- **helpful bị loại.** Recall = 0.30 (tp 9 / (tp 9 + fn 21)) và κ = 0.375, đều dưới FLOORS. Judge này bỏ sót 21 trên 30 reply mà người đánh FAIL. Nếu dùng nó làm gate, 70% reply có lỗi sẽ lọt qua. Precision = 1.0 không cứu được, vì khi judge nói FAIL thì gần như chắc đúng, nhưng nó gần như không bao giờ nói FAIL. Đọc từng dòng bất đồng thì thấy 18 trên 21 case `fn` có `human_failure` = "sai tiền" (ledger ghi số khác). Judge không thấy ledger nên **về cấu trúc** không thể chấm đúng tiêu chí này. Tiền phải chấm bằng code. Rogan-Gladen nâng tỉ lệ fail từ 0.09 lên 0.30 (khớp tỉ lệ người đánh FAIL 30/100), cho thấy chênh lệch rất lớn. Nhưng hiệu chỉnh chỉ sửa được *tỉ lệ tổng*, không cho biết *reply nào* sai, nên vẫn không dùng được để chặn từng PR.
- **tone_ok dùng được** cho giọng văn: bắt 24/30 reply người đánh FAIL (R = 0.8), 24/28 lần báo FAIL là đúng (P = 0.857), κ = 0.757. Chỉ dùng làm metric theo dõi; **không** dùng cho tiền hay approval (quy tắc của lab). Trong `metric_spec.yaml` hiện chưa có metric judge nào, vì MockLLM agent không sinh reply tự do để chấm.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí), và mình đã đọc các bất đồng trước khi sửa rubric. Rubric sửa xong cần **nhãn người mới** trên một tập held-out mới thì mới biết κ / P / R thật. Có 1 nhãn người sai (H-081), nên nhãn người cũng cần kiểm tra chéo.
