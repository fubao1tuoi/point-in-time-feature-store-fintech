# Point-in-Time golden fixture

## 1. Mục đích

`fixtures/golden_transactions.csv` là input nhỏ được thiết kế bằng tay để review và
kiểm thử PIT feature engine. Dataset không lấy mẫu ngẫu nhiên từ IEEE-CIS; mỗi row tồn
tại để tạo một edge case có expected result duy nhất.

Fixture chỉ có các cột tối thiểu mà 10 MVP features cần:

| Column | Vai trò |
|---|---|
| `TransactionID` | Observation ID và same-timestamp tie-breaker. |
| `event_time` | Cutoff và rolling-window time. |
| `TransactionAmt` | Source cho sum/average/maximum. |
| `ProductCD` | Source cho distinct-product count. |
| `card_entity_id` | Secondary entity view. |
| `card_address_entity_id` | Primary entity view. |
| `fixture_case` | Ghi mục đích test; không phải model/feature input. |

Entity IDs dùng tên dễ đọc (`ce_card_a`, `cae_card_a_addr_1`) thay vì hash thật để có
thể tính expected values bằng tay. Semantics grouping vẫn giống Silver entity IDs.

## 2. Physical order

CSV cố ý không được sắp theo `event_time` hoặc `TransactionID`. PIT engine phải order
bằng tuple `(event_time, TransactionID)`, không dựa vào thứ tự dòng/file. Golden test về
sau có thể shuffle thêm input và phải nhận cùng output.

## 3. Logical order và mục đích từng row

| ID | Time | Amount | Product | Secondary | Primary | Case chính |
|---:|---|---:|---|---|---|---|
| 101 | 01/01 00:00 | 10 | W | card A | card A + addr 1 | Observation đầu tiên, không có history. |
| 102 | 08/01 00:00 | 20 | C | card A | card A + addr 1 | ID 101 nằm đúng biên bắt đầu window 7 ngày. |
| 103 | 08/01 00:00 | 30 | H | card A | card A + addr 1 | Cùng timestamp với 102; ID 102 nhỏ hơn nên được dùng. |
| 201 | 08/01 00:00 | 999 | R | card B | card B + addr 1 | Entity khác, không được trộn vào card A. |
| 501 | 08/01 00:10 | 60 | C | card A | card A + addr 2 | Cùng secondary nhưng khác primary; chỉ card view chia sẻ history. |
| 301 | 08/01 00:15 | 40 | S | card A | null | Primary view phải null, secondary vẫn tính được. |
| 401 | 08/01 00:20 | 50 | W | null | null | Cả hai entity views phải null. |
| 104 | 08/01 00:30 | null | null | card A | card A + addr 1 | Count vẫn tăng; amount/product aggregates bỏ null. |
| 105 | 08/01 01:00 | 70 | R | card A | card A + addr 1 | Rows lúc 00:00 nằm đúng biên window 1 giờ. |
| 106 | 09/01 00:00 | 80 | W | card A | card A + addr 1 | Rows ngày 08/01 00:00 nằm đúng biên 24 giờ. |

Tất cả timestamps dùng UTC năm synthetic timeline của project.

## 4. Edge-case coverage

| Required case | Rows tạo case |
|---|---|
| No history | 101; 201 cho entity B |
| Event trước cutoff được dùng | Các observation sau 101 của card A |
| Future event bị loại | Ví dụ output của 102/103 không được thấy 104/105/106 |
| Current event bị loại | Mọi row |
| Same timestamp | 102 và 103 |
| Inclusive 1-hour boundary | 102/103 → 105 |
| Inclusive 24-hour boundary | 102/103 → 106 |
| Inclusive 7-day boundary | 101 → 102/103 |
| Entity isolation | 201 không ảnh hưởng card A |
| Secondary same, primary different | 501 so với card A + addr 1 |
| Null primary, secondary available | 301 |
| Null cả hai entities | 401 |
| Null amount và product | 104 |
| Physical-order independence | CSV được lưu không theo logical order |

## 5. Expected output

Expected 20 feature columns nằm tại `fixtures/golden_expected_features.csv`. Giá trị đã
được tính/review bằng tay trong `GOLDEN_EXPECTED_REVIEW.md`, sau đó đối chiếu bằng một
calculator độc lập. Expected không được sinh từ PIT engine ở Mốc 5, tránh test lặp lại
cùng một lỗi của implementation.

Trong expected CSV, `null` biểu diễn null thật; không có ô output trống mơ hồ. Future
golden tests phải parse `null` trước khi so sánh output engine.

## 6. Observation-layer test

Chạy:

```powershell
python -m pytest tests/point_in_time/test_observations.py -v
```

Test kiểm tra mỗi input transaction tạo đúng một observation, `prediction_time` bằng
`event_time`, source columns được giữ và null/duplicate grain violations làm job fail.
Kết quả hiện tại phải là `6 passed`.

## 7. Full feature-engine correctness test

Chạy:

```powershell
python -m pytest tests/point_in_time/test_feature_computation.py -v
```

Tám tests kiểm tra 200 expected values của hai entity views, output grain, PIT cutoff,
same timestamp, window boundaries, no-history/null semantics, append-only invariance và
deterministic rerun. Kết quả yêu cầu là `8 passed`.
