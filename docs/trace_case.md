# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-013 --seed 11
python -m lab9.trace_case --shape fixed --claim C-013 --seed 11   # đối chứng
```

Output thật (cắt bớt payload của `handoff` và `investigator`):
```
== seeded_regression C-013@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {... "claim_id": "C-013", "allowed_tools": ["lookup_order", "lookup_policy", "compute_compensation"] ...}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-505", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], "parts": {"SHIP-LATE-03": 35000}}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 35000}
   5 proposal           {"amount_vnd": 0}
   6 reply              {"text": "Dạ, đơn O-505 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
-- ledger vs label
  refund_vnd     ledger=0        label=0
  refund_count   ledger=0        label=0
  status         result=denied   label=denied
```

## Case: `seeded_regression C-013@11`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-013@11`, item E-013, report `reports/eval_seeded_regression.json`, run ID `E-seeded_regression-20261118-e43e` |
| Triệu chứng | **Ledger đúng** (0đ, khớp nhãn) và **status đúng** (`denied`), nhưng Lab 8 vẫn FAIL vì `proposal_mismatch`: result báo `proposal_amount = 0`, nhãn yêu cầu 35.000. Nhãn đòi `policy_denied: true`, tức là host phải là bên từ chối, nhưng ledger không có audit event `policy_denied`. Reply chỉ nói "chưa đủ điều kiện", không nêu số tiền, nên `reply_matches_ledger` không bắt được. Ở 4 grader cũ, chỉ `pass_rate` fail. |
| Bước sai đầu tiên | **Event 5** `proposal {"amount_vnd": 0}`: agent tự trừ 35.000 đã hoàn trước đó khỏi quote 35.000 và ra đề xuất 0đ. Vì đề xuất 0đ nên agent không gọi `issue_refund`, và host không có cơ hội từ chối. |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) và 2 (`investigator`, `visible: true`, đơn O-505 của đúng P-100) giống hệt `fixed`. Event 3 `quote` = 35.000 với `SHIP-LATE-03`, cũng giống `fixed`. Event 4 `refund_history` chỉ là một lần đọc (read-only): `honest_refactor` cũng gọi đúng tool này (`extra_lookup`) mà vẫn đúng. Vậy chỗ sai đầu tiên là lúc kết quả đọc được *dùng để sửa đề xuất*, tức event 5. |
| Failure mode | **FM-05** pre_deducted (xem `docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-013@11`: event 1–3 giống hệt, **không có** event `refund_history` hay `proposal`, event 4 là `reply`. Agent gửi 35.000 cho host, host từ chối (`order_already_refunded`) và ghi `policy_denied`. Kết quả: Lab 8 PASS (`ok`). |
| Regression test | `tests/test_lab9_trace_case.py`, gồm hai test: `test_lab9_trace_case_c013_pre_deducted_is_caught` (assert ledger = 0, có event `proposal` amount 0, và grader `HostDenialKept` trả `False`) và `test_lab9_trace_case_c013_fixed_passes` (assert `fixed` PASS Lab 8 và `HostDenialKept` trả `True`). Cả hai đã chạy xanh (`pytest -q -m student -o addopts= -k "lab9 and not advanced"`), và CI cũng chạy chúng. Từ case này mình thêm metric `host_denial_kept` vào `config/metric_spec.yaml`. Trước khi có metric đó, `lab9.mutation --detect` chỉ giải thích được **75%** số dòng fail của `seeded_regression`, đúng 5 dòng E-013 không grader nào bắt. Sau khi thêm: **100%**, báo nhầm 0%. |
| Chưa chắc chắn | Trace không cho biết agent "định" làm gì: không biết agent cố ý tự từ chối hay chỉ tính nhầm. Trace cũng không chứng minh host *sẽ* từ chối nếu được gọi; điều đó chỉ được suy ra từ lần chạy `fixed` cùng seed. Grader `HostDenialKept` dựa vào nhãn `policy_denied` và audit event `policy_denied` của Lab 8: nếu host đổi tên event, grader sẽ báo sai. Ngoài ra, trên MockLLM, lỗi này xuất hiện ở cả 5 seed. Với LLM thật, tỉ lệ có thể khác. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
