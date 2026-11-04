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

## 2. Surrogate entity contract v1

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

## 3. Entity invariants

- Components được xử lý như categorical codes.
- `1001` và `1001.0` phải có cùng canonical representation.
- Cùng input và version phải tạo cùng ID.
- Primary ID null nếu `card1` hoặc `addr1` null.
- Secondary ID null nếu `card1` null.
- Không dùng sentinel chung cho missing components.
- `isFraud` không được tham gia entity resolution.
- Thay đổi logic entity bắt buộc tạo version mới.

## 4. Feature contract

- Primary aggregate dùng `card_address_entity_id` và output prefix `card_addr_`.
- Secondary aggregate dùng `card_entity_id` và output prefix `card_`.
- Khi primary tồn tại, phải tính cả hai feature views.
- Khi thiếu `addr1`, `card_addr_*` là null nhưng `card_*` vẫn được tính nếu có `card1`.
- Không được ghi secondary aggregate vào một cột `card_addr_*`.
- Mọi historical feature phải dùng cutoff `source_event_time < observation_time`.

Coverage quan sát trên train:

```text
primary assigned coverage   = 88,87%
secondary assigned coverage = 100,00%
```

Chi tiết quyết định: [`entity_key_decision.md`](./entity_key_decision.md).
