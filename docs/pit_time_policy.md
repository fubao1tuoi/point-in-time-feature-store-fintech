# PIT time and same-timestamp policy

## 1. Trạng thái và phạm vi

**Trạng thái:** Chốt cho Feature Registry v1 ngày 2026-11-06.

Tài liệu này định nghĩa một historical event có được phép tham gia feature của một
observation hay không. Quy tắc áp dụng giống nhau cho primary view
`card_address_entity_id` và secondary view `card_entity_id`.

## 2. Observation key và thứ tự chuẩn

Mỗi observation được định danh và sắp xếp bằng tuple:

```text
(event_time, TransactionID)
```

Thứ tự chuẩn là:

```text
event_time ASC, TransactionID ASC
```

`event_time` là thời gian nghiệp vụ chính. `TransactionID` chỉ là tie-breaker kỹ thuật
khi nhiều transaction có cùng `event_time`.

Các điều kiện đầu vào bắt buộc:

- `event_time` không null.
- `TransactionID` không null và duy nhất trong phạm vi feature computation.
- `TransactionID` đã được cast sang `BIGINT` trước khi so sánh.
- Duplicate ID có nội dung xung đột phải làm pipeline fail.

## 3. Cutoff rule

Với history row `h` và observation `o` của cùng entity, `h` chỉ hợp lệ khi:

```text
h.event_time < o.event_time
OR
(
  h.event_time = o.event_time
  AND h.TransactionID < o.TransactionID
)
```

Cách viết ngắn gọn:

```text
(h.event_time, h.TransactionID)
    <
(o.event_time, o.TransactionID)
```

Tên policy trong Feature Registry:

```text
cutoff_policy: lexicographic_strict_before
same_timestamp_policy: lower_transaction_id_is_earlier
current_event_policy: exclude
```

## 4. Current-event exclusion

Observation hiện tại không bao giờ được tính vào historical features của chính nó.
Vì `TransactionID` là duy nhất, tuple của current row bằng tuple observation, không nhỏ
hơn tuple observation nên tự động bị loại.

Ví dụ observation `(10:00:00, 105)`:

| History candidate | Được dùng? | Lý do |
|---|---|---|
| `(09:59:59, 999)` | Có | `event_time` sớm hơn. |
| `(10:00:00, 104)` | Có | Cùng timestamp nhưng ID nhỏ hơn. |
| `(10:00:00, 105)` | Không | Chính current event. |
| `(10:00:00, 106)` | Không | Cùng timestamp nhưng ID lớn hơn. |
| `(10:00:01, 1)` | Không | Event tương lai. |

## 5. Same-timestamp example

Ba giao dịch của cùng entity có cùng timestamp:

```text
(10:00:00, 101) amount=10
(10:00:00, 102) amount=20
(10:00:00, 103) amount=30
```

Expected historical count và sum:

| Observation | Eligible same-time history | Count | Sum |
|---|---|---:|---:|
| ID 101 | Không có | 0 | 0 |
| ID 102 | ID 101 | 1 | 10 |
| ID 103 | ID 101, 102 | 2 | 30 |

Rule tạo kết quả deterministic dù engine đọc Parquet theo file order khác nhau.

## 6. Window boundary

Với window có độ dài `W`, history row phải đồng thời thỏa:

```text
o.event_time - W <= h.event_time
```

và cutoff tuple ở mục 3. Như vậy:

- Biên bắt đầu window là **inclusive**.
- Observation/current tuple là **exclusive**.
- Event sau observation luôn bị loại.

Ví dụ observation lúc `10:00` và window 24 giờ:

```text
05/11 10:00:00  → được tính nếu tuple đứng trước observation
06/11 09:59:59  → được tính
06/11 10:00:00  → áp dụng TransactionID tie-breaker
```

## 7. Null entity và entity isolation

- History chỉ được dùng khi history và observation có cùng non-null entity ID.
- Observation thiếu primary entity nhận `card_addr_* = null`.
- Secondary `card_*` vẫn được tính nếu `card_entity_id` tồn tại.
- History của entity A không bao giờ được đưa vào feature của entity B.

## 8. Vì sao chọn policy này?

Chỉ dùng `history_time < observation_time` sẽ loại toàn bộ giao dịch cùng giây. Điều đó
an toàn nhưng bỏ thông tin thứ tự mà dataset có thể biểu diễn qua `TransactionID`.
Ngược lại, đưa toàn bộ giao dịch cùng timestamp vào history sẽ khiến các event nhìn thấy
lẫn nhau và current event có thể tự đếm chính nó.

Tuple `(event_time, TransactionID)` cung cấp:

- Một total order deterministic.
- Loại current event rõ ràng.
- Kết quả không phụ thuộc file/row order.
- Expected output same-timestamp có thể tính và test bằng tay.

## 9. Giả định và giới hạn

IEEE-CIS không công bố một sequence number riêng cho các event trong cùng giây. Project
dùng `TransactionID` tăng dần làm tie-breaker kỹ thuật theo modeling assumption; không
khẳng định ID là timestamp hay thứ tự nghiệp vụ chính thức.

Khi áp dụng cho production:

- Chỉ dùng rule này nếu source xác nhận ID/sequence phản ánh thứ tự event.
- Nếu không có sequence đáng tin cậy, chọn batch semantics: các event cùng timestamp
  không nhìn thấy nhau.
- Late-arriving row có tuple nhỏ hơn một observation đã materialize có thể làm thay đổi
  historical feature của observation đó. Khi đó phải backfill/version output; nếu cần
  tái hiện “hệ thống biết gì tại thời điểm xử lý”, phải bổ sung `ingestion_time` và
  bitemporal cutoff.
- Thay đổi same-timestamp policy là thay đổi feature semantics và bắt buộc tăng feature
  version.

## 10. Golden-test cases bắt buộc

Feature engine ở Mốc 5 phải có test cho:

1. Event sớm hơn timestamp được dùng.
2. Event tương lai bị loại.
3. Current event bị loại.
4. Cùng timestamp, ID nhỏ hơn được dùng.
5. Cùng timestamp, ID lớn hơn bị loại.
6. Event đúng biên bắt đầu window được dùng.
7. Entity khác không bị trộn.
8. Null entity trả về null theo feature-view contract.
9. Thay file/row order không làm đổi kết quả.
10. Thêm future tuple không làm đổi feature của observation quá khứ.
