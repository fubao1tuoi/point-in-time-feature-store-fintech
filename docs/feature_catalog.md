# Feature Catalog — Historical Transaction Features v1

## 1. Mục đích và nguồn sự thật

Catalog này mô tả các historical features mà Point-in-Time Feature Store cung cấp cho
MVP phát hiện gian lận giao dịch. Tài liệu dành cho người xây training dataset, model,
test và demo.

Nguồn định nghĩa máy đọc:

- Primary registry: [`transaction_velocity_v1.yaml`](../configs/features/transaction_velocity_v1.yaml)
- Secondary registry: [`transaction_velocity_card_v1.yaml`](../configs/features/transaction_velocity_card_v1.yaml)

Các YAML là nguồn thực thi; catalog giải thích semantics cho con người. Mọi thay đổi
aggregation, window, entity, cutoff, default hoặc output type phải cập nhật cả registry,
validator, catalog và feature version.

## 2. Phạm vi v1

```text
Feature-set version : 1
Source              : silver_transactions
Logical features    : 10
Entity views        : 2
Output columns      : 20
Owner               : data-engineering
```

V1 chỉ gồm các historical features có nguồn và công thức giải thích được. Không dùng
`isFraud`, `C*`, `D*`, `M*` hoặc `V*` để tạo các aggregate trong catalog này.

## 3. Hai entity views

| View | Entity key | Components | Prefix | Ý nghĩa |
|---|---|---|---|---|
| Primary | `card_address_entity_id` | `card1`, `addr1` | `card_addr_` | Lịch sử cụ thể theo card code và billing region. |
| Secondary | `card_entity_id` | `card1` | `card_` | Lịch sử rộng hơn theo card code, coverage cao hơn. |

Mỗi logical feature được tính độc lập trên cả hai view. Ví dụ:

```text
card_addr_txn_count_24h → count theo card1 + addr1
card_txn_count_24h      → count theo card1
```

Khi primary tồn tại, model nhận cả hai view. Secondary không được ghi thay vào cột
primary.

## 4. Quy tắc Point-in-Time dùng chung

Observation được định danh bằng:

```text
(event_time, TransactionID)
```

History row `h` hợp lệ cho observation `o` khi cùng non-null entity và:

```text
(h.event_time, h.TransactionID)
    <
(o.event_time, o.TransactionID)
```

Hệ quả:

- Current transaction không tự đi vào feature của chính nó.
- Future transaction bị loại.
- Cùng timestamp, `TransactionID` nhỏ hơn được xem là đứng trước.
- Biên bắt đầu rolling window là inclusive.
- Kết quả không phụ thuộc physical row/file order.

Chi tiết: [`pit_time_policy.md`](./pit_time_policy.md).

## 5. Null và no-history semantics

| Trường hợp | Output |
|---|---|
| Entity ID của view là null | Toàn bộ feature của view bằng null. |
| Entity hợp lệ nhưng không có history trong window | Count, sum và distinct count bằng 0. |
| Không có giá trị để tính average/max | Null. |
| Không có previous transaction | Recency bằng null. |
| `TransactionAmt` null | Bỏ qua trong sum/avg/max nhưng row vẫn được tính trong transaction count. |
| `ProductCD` null | Bỏ qua trong distinct product count. |

Phân biệt quan trọng:

```text
0    → entity được resolve, nhưng không có event/value lịch sử trong window
null → không resolve được entity hoặc metric chưa thể tính
```

## 6. Danh sách feature tổng hợp

| Logical feature | Aggregation | Source value | Window | Output type | No history |
|---|---|---|---|---|---|
| `txn_count_1h` | Count rows | — | 1 giờ | BIGINT | `0` |
| `txn_count_24h` | Count rows | — | 24 giờ | BIGINT | `0` |
| `txn_count_7d` | Count rows | — | 7 ngày | BIGINT | `0` |
| `amount_sum_1h` | Sum | `TransactionAmt` | 1 giờ | DOUBLE | `0.0` |
| `amount_sum_24h` | Sum | `TransactionAmt` | 24 giờ | DOUBLE | `0.0` |
| `amount_sum_7d` | Sum | `TransactionAmt` | 7 ngày | DOUBLE | `0.0` |
| `amount_avg_24h` | Average | `TransactionAmt` | 24 giờ | DOUBLE | null |
| `amount_max_7d` | Maximum | `TransactionAmt` | 7 ngày | DOUBLE | null |
| `seconds_since_previous_txn` | Time difference | `event_time` | Không giới hạn | BIGINT | null |
| `distinct_product_count_7d` | Count distinct | `ProductCD` | 7 ngày | BIGINT | `0` |

## 7. Chi tiết từng logical feature

### 7.1. `txn_count_1h`

**Outputs:** `card_addr_txn_count_1h`, `card_txn_count_1h`
**Công thức:** số eligible historical rows trong `[event_time - 1h, observation)`.
**Mục đích:** phát hiện burst rất ngắn hạn như card testing, bot hoặc nhiều giao dịch
liên tiếp trong vài phút.
**Không có history:** `0`.

### 7.2. `txn_count_24h`

**Outputs:** `card_addr_txn_count_24h`, `card_txn_count_24h`
**Công thức:** số eligible historical rows trong 24 giờ.
**Mục đích:** đo cường độ hoạt động trong ngày, kể cả khi các giao dịch được giãn ra nên
window một giờ không bắt được.
**Không có history:** `0`.

### 7.3. `txn_count_7d`

**Outputs:** `card_addr_txn_count_7d`, `card_txn_count_7d`
**Công thức:** số eligible historical rows trong bảy ngày.
**Mục đích:** tạo baseline tần suất nhiều ngày và cho phép model so sánh burst gần nhất
với mức hoạt động cả tuần.
**Không có history:** `0`.

### 7.4. `amount_sum_1h`

**Outputs:** `card_addr_amount_sum_1h`, `card_amount_sum_1h`
**Công thức:** tổng non-null `TransactionAmt` của eligible history trong một giờ.
**Mục đích:** đo tốc độ tích lũy exposure; cùng số giao dịch nhưng tổng 25 USD và 2.500
USD có mức rủi ro khác nhau.
**Không có amount hợp lệ:** `0.0`.

### 7.5. `amount_sum_24h`

**Outputs:** `card_addr_amount_sum_24h`, `card_amount_sum_24h`
**Công thức:** tổng non-null `TransactionAmt` trong 24 giờ.
**Mục đích:** phát hiện tổng exposure lớn trong ngày dù giao dịch không tập trung trong
một giờ.
**Không có amount hợp lệ:** `0.0`.

### 7.6. `amount_sum_7d`

**Outputs:** `card_addr_amount_sum_7d`, `card_amount_sum_7d`
**Công thức:** tổng non-null `TransactionAmt` trong bảy ngày.
**Mục đích:** đo exposure tích lũy nhiều ngày; đọc cùng sum 24 giờ để nhận biết phần lớn
giá trị tuần có vừa dồn vào một ngày hay không.
**Không có amount hợp lệ:** `0.0`.

### 7.7. `amount_avg_24h`

**Outputs:** `card_addr_amount_avg_24h`, `card_amount_avg_24h`
**Công thức:** trung bình non-null `TransactionAmt` trong 24 giờ.
**Mục đích:** phân biệt nhiều giao dịch nhỏ với ít giao dịch lớn khi tổng amount giống
nhau; biểu diễn kích thước giao dịch điển hình gần đây.
**Không có amount hợp lệ:** null.

### 7.8. `amount_max_7d`

**Outputs:** `card_addr_amount_max_7d`, `card_amount_max_7d`
**Công thức:** non-null `TransactionAmt` lớn nhất trong bảy ngày.
**Mục đích:** giữ tín hiệu extreme event mà sum hoặc average có thể che khuất. Maximum
phải được đọc cùng các feature khác vì một outlier hợp lệ cũng có thể tạo giá trị cao.
**Không có amount hợp lệ:** null.

### 7.9. `seconds_since_previous_txn`

**Outputs:** `card_addr_seconds_since_previous_txn`, `card_seconds_since_previous_txn`
**Công thức:** số giây giữa observation và eligible historical transaction gần nhất của
cùng entity.
**Mục đích:** phân biệt giao dịch trước cách vài giây với giao dịch trước cách gần một
giờ, dù cả hai có cùng count trong window.
**Window:** không giới hạn; tìm prior event gần nhất trong history hợp lệ.
**Không có prior event:** null.

### 7.10. `distinct_product_count_7d`

**Outputs:** `card_addr_distinct_product_count_7d`, `card_distinct_product_count_7d`
**Công thức:** số `ProductCD` non-null khác nhau trong eligible history bảy ngày.
**Mục đích:** đo độ đa dạng hành vi mà count và amount không biểu diễn.
**Không có product value hợp lệ:** `0`.
**Giới hạn:** `ProductCD` là code đã ẩn nghĩa; không tự gán ý nghĩa sản phẩm cho từng
giá trị.

## 8. Danh sách 20 output columns

### Primary — `card_address_entity_id`

```text
card_addr_txn_count_1h
card_addr_txn_count_24h
card_addr_txn_count_7d
card_addr_amount_sum_1h
card_addr_amount_sum_24h
card_addr_amount_sum_7d
card_addr_amount_avg_24h
card_addr_amount_max_7d
card_addr_seconds_since_previous_txn
card_addr_distinct_product_count_7d
```

### Secondary — `card_entity_id`

```text
card_txn_count_1h
card_txn_count_24h
card_txn_count_7d
card_amount_sum_1h
card_amount_sum_24h
card_amount_sum_7d
card_amount_avg_24h
card_amount_max_7d
card_seconds_since_previous_txn
card_distinct_product_count_7d
```

## 9. Ví dụ cách đọc feature

Giả sử observation có:

```text
card_addr_txn_count_1h  = 4
card_addr_txn_count_24h = 5
card_addr_txn_count_7d  = 6
card_addr_amount_sum_1h = 1800
card_addr_seconds_since_previous_txn = 20
```

Có thể diễn giải: card-address entity có sáu giao dịch lịch sử trong tuần, năm trong 24
giờ và bốn trong giờ gần nhất; tổng amount một giờ là 1.800 và prior event chỉ cách 20
giây. Đây là historical context cho model, không phải rule khẳng định transaction là
fraud.

## 10. Quy tắc sử dụng

- Không dùng `TransactionID` như model feature; nó chỉ định danh observation/tie-break.
- Không dùng `isFraud` trong historical aggregate.
- Không so sánh trực tiếp primary và secondary như cùng một population; entity grain
  khác nhau.
- Giữ các availability fields như `has_card_address_entity` hoặc
  `entity_resolution_level` để model phân biệt null do entity resolution.
- Training/validation/test phải chia theo thời gian, không random split làm đánh giá chính.
- Chỉ materialize feature khi Feature Registry validator pass.

## 11. Versioning và mở rộng

Feature-set v1 giữ 10 logical features để hoàn thành pipeline correctness trong thời hạn
năm tuần. Các feature 30 ngày, standard deviation, email/device diversity hoặc ratio là
stretch goals, chỉ thêm sau benchmark.

Bắt buộc tăng version nếu thay đổi:

- entity key hoặc hash semantics;
- aggregation/value column;
- window hoặc boundary;
- same-timestamp/current-event policy;
- null/no-history semantics;
- output type hoặc ý nghĩa feature.

Chỉ sửa description không làm thay đổi feature semantics.

## 12. Validation

Chạy trước feature computation:

```powershell
python pipelines/validate_feature_registry.py
```

Kết quả v1 hợp lệ phải báo hai registry có 10 feature và tổng cộng 20 output columns.
Chi tiết schema: [`IMPLEMENTATION_LOG.md`](./IMPLEMENTATION_LOG.md#feature-registry-schema-và-validator).
