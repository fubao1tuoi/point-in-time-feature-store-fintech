# Data contract

Data contract được cập nhật sau dataset profiling và surrogate entity analysis.

## 1. Source invariants

- `TransactionID` không null và duy nhất trong transaction source.
- `TransactionDT` không null và không âm.
- `TransactionAmt` là numeric và không âm.
- `isFraud` thuộc `{0, 1}` trong training data.
- Identity là dữ liệu tùy chọn và phải được nối bằng left join.

### Time configuration

- Timeline kỹ thuật dùng synthetic epoch cố định `2017-01-01T00:00:00Z` (UTC).
- `event_time = synthetic_epoch + TransactionDT seconds`.
- Synthetic epoch không phải ngày giao dịch thật; nó chỉ bảo toàn thứ tự và khoảng cách thời gian.
- Đổi synthetic epoch là thay đổi data contract và yêu cầu rebuild toàn bộ Silver/PIT outputs.

## 2. Bronze ingestion contract

Bronze snapshot của mỗi source được ghi tại:

```text
data/bronze/<source_name>/data.parquet
```

Quy tắc bảo toàn dữ liệu:

- Mọi cột nguồn được lưu dưới dạng UTF-8 string; Bronze không cast kiểu nghiệp vụ.
- Chuỗi rỗng được giữ là chuỗi rỗng; việc chuyển missing value thành null thuộc Silver.
- Tên, thứ tự cột và thứ tự dòng nguồn được giữ nguyên.
- `_source_row_number` bắt đầu từ 1 và cho phép truy ngược vị trí dòng dữ liệu.
- Pipeline chỉ publish sau khi toàn bộ source được stage và đối soát thành công.

Metadata được bổ sung cho mỗi dòng:

```text
_ingestion_run_id
_source_name
_source_file
_source_checksum_sha256
_ingested_at_utc
_source_row_number
```

Run-level manifest được ghi tại
`reports/generated/bronze_ingestion_manifest.json`, bao gồm checksum, row count,
column count, output path, output size và runtime của từng source.

## 3. Silver transaction contract

Canonical dataset được ghi dạng partitioned Parquet tại:

```text
data/silver/transactions/
  dataset_split=<train|test>/
    event_month=<YYYY-MM>/
```

Quy tắc chuyển đổi:

- Chuỗi rỗng từ Bronze được chuyển thành null.
- `TransactionID`, `TransactionDT` → `BIGINT`.
- `TransactionAmt` và các nhóm numeric → `DOUBLE`.
- `isFraud` → `TINYINT`; test rows nhận null.
- Encoded categorical/card/address/email/device fields giữ dạng string.
- Test identity `id-01`–`id-38` được chuẩn hóa về `id_01`–`id_38`.
- Exact duplicate rows được giữ một bản; duplicate `TransactionID` có nội dung xung
  đột làm pipeline fail.
- Transaction–identity enrichment luôn dùng left join.

Các trường được tạo:

```text
event_time
event_date
event_month
dataset_split
has_identity
card_entity_id
card_address_entity_id
has_card_address_entity
entity_resolution_level
card_entity_version
card_address_entity_version
_silver_run_id
_silver_created_at_utc
_silver_schema_version
```

Silver run chỉ được publish khi row count, uniqueness, identity coverage, required
types, label domain và event-time checks đều pass. Semantic fingerprint loại metadata
động của các lần chạy (`run_id`, `ingested_at`, `silver_created_at`) nhưng vẫn giữ
source checksum và source row number. Vì vậy chạy lại Bronze với cùng raw content
không làm thay đổi fingerprint nghiệp vụ của Silver.

## 4. Surrogate entity contract v1

MVP cung cấp hai entity view độc lập:

| Vai trò | Output column | Components | Prefix |
|---|---|---|---|
| Primary | `card_address_entity_id` | `card1`, `addr1` | `cae_v1_` |
| Secondary | `card_entity_id` | `card1` | `ce_v1_` |

Các cột metadata bắt buộc:

```text
has_card_address_entity
entity_resolution_level
card_address_entity_version
card_entity_version
```

`entity_resolution_level` chỉ nhận một trong ba giá trị:

```text
card_address | card_only | unresolved
```

## 5. Entity invariants

- Components được xử lý như categorical codes.
- `1001` và `1001.0` phải có cùng canonical representation.
- Cùng input và version phải tạo cùng ID.
- Primary ID null nếu `card1` hoặc `addr1` null.
- Secondary ID null nếu `card1` null.
- Không dùng sentinel chung cho missing components.
- `isFraud` không được tham gia entity resolution.
- Thay đổi logic entity bắt buộc tạo version mới.

## 6. Feature contract

- Primary aggregate dùng `card_address_entity_id` và output prefix `card_addr_`.
- Secondary aggregate dùng `card_entity_id` và output prefix `card_`.
- Khi primary tồn tại, phải tính cả hai feature views.
- Khi thiếu `addr1`, `card_addr_*` là null nhưng `card_*` vẫn được tính nếu có `card1`.
- Không được ghi secondary aggregate vào một cột `card_addr_*`.
- Mọi historical feature dùng strict lexicographic cutoff:
  `(history.event_time, history.TransactionID) <`
  `(observation.event_time, observation.TransactionID)`.
- Với cùng `event_time`, `TransactionID` nhỏ hơn được coi là đứng trước.
- Current event luôn bị loại; kết quả không được phụ thuộc physical row/file order.
- Biên bắt đầu rolling window là inclusive; cutoff observation là exclusive.
- Thay đổi same-timestamp policy bắt buộc tăng feature version.

Coverage quan sát trên train:

```text
primary assigned coverage   = 88,87%
secondary assigned coverage = 100,00%
```

### 6.1. MVP feature set v1

Mười định nghĩa logic được áp dụng độc lập cho cả primary và secondary view, tạo 20
output columns:

| Logical feature | Aggregation | Window |
|---|---|---|
| `txn_count_1h` | Count history rows | 1 giờ |
| `txn_count_24h` | Count history rows | 24 giờ |
| `txn_count_7d` | Count history rows | 7 ngày |
| `amount_sum_1h` | Sum `TransactionAmt` | 1 giờ |
| `amount_sum_24h` | Sum `TransactionAmt` | 24 giờ |
| `amount_sum_7d` | Sum `TransactionAmt` | 7 ngày |
| `amount_avg_24h` | Average `TransactionAmt` | 24 giờ |
| `amount_max_7d` | Maximum `TransactionAmt` | 7 ngày |
| `seconds_since_previous_txn` | Seconds from previous eligible event | Không giới hạn window |
| `distinct_product_count_7d` | Count distinct non-null `ProductCD` | 7 ngày |

Output dùng prefix `card_addr_` hoặc `card_`. Ví dụ:

```text
card_addr_txn_count_24h
card_txn_count_24h
```

Null/default contract:

- Entity tồn tại nhưng không có eligible history: count, sum và distinct count bằng 0.
- Entity tồn tại nhưng không có giá trị hợp lệ: average, maximum và recency bằng null.
- Null `TransactionAmt` bị bỏ qua trong sum/average/max; transaction vẫn được tính cho
  transaction count.
- Null `ProductCD` bị bỏ qua trong distinct count.
- Nếu entity ID của view là null, toàn bộ feature của view đó là null để phân biệt
  “không resolve được entity” với “entity hợp lệ nhưng chưa có lịch sử”.
- `isFraud` không được dùng trong bất kỳ MVP feature nào.

Chi tiết quyết định: [`entity_key_decision.md`](./entity_key_decision.md).

Chi tiết time/cutoff contract: [`pit_time_policy.md`](./pit_time_policy.md).
