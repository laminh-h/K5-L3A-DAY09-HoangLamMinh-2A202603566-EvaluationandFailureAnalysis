# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-002@11

Output (rút gọn):
```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {"contract_version": "handoff.v1", "facts": {}, "claim_id": "C-002", ...}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-202", ..., "delay_days": 2 ...
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `reports/eval_seeded_regression.json` run ID `E-seeded_regression-20261117-873a` (row `E-002`, seed 11) |
| Triệu chứng | Lab 8 grader FAIL `status resolved != denied`; `refund_amount_correct` = False (ledger 20.000đ, nhãn 0); `db_fact_kept` = False. Reply nói "đã hoàn 20.000đ", **khớp ledger**, nên câu trả lời trôi chảy và nhất quán che mất việc khoản hoàn này không được phép có. |
| Bước sai đầu tiên | **Event 3** `model_override` · payload `{"delay_days": 5}`: agent ghi đè `delay_days` của DB (2) bằng số ngày trong ticket ("Đơn giao trễ 5 ngày"). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract (`facts: {}`, chỉ cho tool đọc). Event 2 `investigator` đọc đúng đơn O-202 với `delay_days: 2` (trễ 2 ngày, không đủ điều kiện hoàn ship). Đến event 2 mọi dữ kiện vẫn đúng; event 3 là chỗ đầu tiên agent thay dữ kiện DB bằng lời khách. Event 4 `quote` 20.000đ chỉ là hệ quả: `compute_compensation` tính đúng trên một đơn đã bị sửa (trễ 5 ngày). |
| Failure mode | **FM-03** ticket_trust (layer model/prompt). Event 5 `refund_history` là bước thừa của FM-05 nhưng không đổi kết quả (đơn chưa hoàn lần nào). |
| Đối chứng | `fixed C-002@11`: event 2 `investigator` y hệt, **không có `model_override`**, event 3 `quote` `{"amount_vnd": 0, "reason": "no_entitlement"}`, reply "chưa đủ điều kiện", ledger 0, status `denied` → PASS. Trên `swarm` lỗi này chỉ xuất hiện ở seed 55 (C-002@55, cùng event 3), đó là điểm yếu cố ý của swarm reference. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_trace_case_first_wrong_step_is_model_override` (event 3 là `model_override`, đè `delay_days` 2 → 5; `fixed` không có event này) và `test_trace_case_graders_fail_on_regression_and_pass_on_fixed` (`DbFactKept`, `RefundAmountCorrect`, `TrialPass` = False trên `seeded_regression`, True trên `fixed`). Đã chạy: **fail đúng trên variant lỗi, pass trên `fixed`**; test có marker `student` và tên chứa `lab9`, nên chạy trong job `eval-gate` (`-k "lab9 and not advanced"`). Ở mức eval set, item E-002 (gắn FM-03) đã phủ claim này trên 5 seed. Gate chặn `seeded_regression` qua `pass_rate` và `refund_amount_correct`. |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent tin ticket: MockLLM không có prompt/logprob, chỉ có công tắc `ticket_trust`. Với LLM thật, cùng triệu chứng có thể đến từ prompt injection hoặc từ parse nhầm. Trace cũng không cho thấy host có nên chặn được hay không: host chỉ kiểm approval/ownership/idempotency, không kiểm lại `delay_days`, nên lỗi này lọt qua mọi guardrail phía host. Cuối cùng, `db_fact_kept` dựa vào việc agent *tự ghi* event `model_override`; một agent "im lặng" (`quiet_override`) vẫn bị `refund_amount_correct` bắt nhưng bước sai đầu tiên sẽ không còn hiện trong trace. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
