# Surrogate Entity Key Decision

## 1. Trạng thái quyết định

**Accepted for MVP — primary và secondary entity, version 1.**

```text
Primary:   card_address_entity_id = SHA-256(v1, card1, addr1)
Secondary: card_entity_id         = SHA-256(v1, card1)
```

Mô hình MVP nhận **cả hai feature set**. Đây không phải hai khóa thay thế lẫn nhau trong cùng một cột; mỗi khóa tạo một nhóm feature có tên và ngữ nghĩa riêng.

## 2. Bối cảnh

IEEE-CIS không cung cấp `customer_id`, `account_id` hoặc định danh thẻ hoàn chỉnh. Project cần surrogate entity để tạo feature lịch sử như số giao dịch theo cửa sổ thời gian, tổng amount và thời gian từ giao dịch trước.

Surrogate entity chỉ là khóa phân nhóm phục vụ nghiên cứu. Nó không chứng minh các giao dịch thuộc cùng một khách hàng hoặc payment card thật.

## 3. Kết quả phân tích chính

| Candidate | Assigned % | Entities | Singleton % | Repeat coverage overall % | Top 1% share % | P50 span days |
|---|---:|---:|---:|---:|---:|---:|
| `card1` | 100,00 | 13.553 | 25,41 | 99,42 | 52,97 | 132,70 |
| `card1 + addr1` | 88,87 | 37.531 | 39,48 | 86,36 | 39,96 | 110,01 |

Chi tiết đầy đủ nằm trong [`reports/entity_key_analysis.md`](../reports/entity_key_analysis.md).

`card1 + addr1` cụ thể hơn và giảm nguy cơ trộn lịch sử giữa các nhóm địa chỉ. `card1` có coverage cao hơn nhưng rộng hơn và bị concentration cao. Vì hai khóa có ưu/nhược điểm bổ sung nhau, MVP giữ cả hai view thay vì ép chúng vào một entity duy nhất.

## 4. Cách routing và tạo feature

### Giao dịch có đủ `card1` và `addr1`

- Tạo cả `card_address_entity_id` và `card_entity_id`.
- Tính cả feature `card_addr_*` và `card_*`.
- `has_card_address_entity = 1`.
- `entity_resolution_level = "card_address"`.

### Giao dịch có `card1` nhưng thiếu `addr1`

- `card_address_entity_id = null` và feature `card_addr_* = null`.
- Vẫn tạo `card_entity_id` và tính feature `card_*`.
- `has_card_address_entity = 0`.
- `entity_resolution_level = "card_only"`.

### Giao dịch thiếu `card1`

- Cả hai entity ID đều null.
- `entity_resolution_level = "unresolved"`.

Đây là **feature-level fallback**: mô hình dùng secondary feature khi primary feature không có. Không được ghi aggregate theo `card1` vào cột mang tên `card_addr_*`, vì như vậy một feature sẽ có hai ngữ nghĩa.

## 5. Vì sao giữ nhóm thiếu `addr1`

Train có 65.706 giao dịch thiếu primary entity, tương đương 11,13%. Nhóm này không nên bị loại:

- Fraud rate của nhóm thiếu `addr1` khoảng 11,78%.
- Fraud rate của nhóm có đủ primary key khoảng 2,46%.

Việc loại nhóm thiếu `addr1` vừa mất dữ liệu vừa có thể tạo selection bias. Secondary view giúp nhóm này vẫn có historical features.

## 6. Quy tắc tạo ID

- Code số nguyên như `1001` và `1001.0` phải có cùng canonical representation.
- Dữ liệu đầu vào phải hữu hạn.
- Không dùng `isFraud`, `TransactionID` hoặc dữ liệu tương lai trong công thức key.
- ID dùng SHA-256 và không chứa trực tiếp raw components.
- Primary có prefix `cae_v1_`; secondary có prefix `ce_v1_`.
- Thiếu bất kỳ component bắt buộc nào thì ID tương ứng là null; không dùng sentinel chung.

Hash chỉ tạo ID deterministic thuận tiện cho join/partition. Nó không biến surrogate entity thành danh tính thật hoặc cơ chế ẩn danh production hoàn chỉnh.

## 7. Feature sets của MVP

| View | Entity key | Prefix output | Coverage train quan sát |
|---|---|---|---:|
| Primary card-address | `card_address_entity_id` | `card_addr_` | 88,87% |
| Secondary card | `card_entity_id` | `card_` | 100,00% |

Ví dụ cùng một transaction có thể nhận:

```text
card_addr_txn_count_24h = 2
card_txn_count_24h      = 9
```

Hai giá trị cùng hợp lệ: giá trị đầu mô tả lịch sử của cặp card-address, giá trị sau mô tả lịch sử rộng hơn của card.

## 8. Invariants bắt buộc

- Cùng components và version phải luôn tạo cùng ID.
- Thay đổi một component phải tạo ID khác.
- Primary chỉ tồn tại khi cả `card1` và `addr1` tồn tại.
- Secondary tồn tại khi `card1` tồn tại.
- Raw components không xuất hiện trong output ID.
- Không dùng label để tạo entity.
- Không trộn hai entity semantics trong cùng một feature column.
- Thay đổi component, canonicalization, hash hoặc null policy phải tăng version.

## 9. Rủi ro và giới hạn

- `card1` có thể gom nhiều đối tượng và tạo hotspot; cần theo dõi skew khi tính rolling feature.
- `card1 + addr1` có thể tách cùng một khách hàng khi billing region thay đổi.
- Project không có ground-truth customer ID để đo chính xác entity resolution.
- Mô hình có thể học mạnh từ trạng thái thiếu `addr1`; cần đánh giá theo time split và theo từng resolution level.
- Mọi rolling feature vẫn phải tuân thủ strict-before cutoff để bảo đảm PIT correctness.

## 10. Implementation

- Cấu hình entity: [`configs/entities.yaml`](../configs/entities.yaml).
- Primary feature set: [`configs/features/transaction_velocity_v1.yaml`](../configs/features/transaction_velocity_v1.yaml).
- Secondary feature set: [`configs/features/transaction_velocity_card_v1.yaml`](../configs/features/transaction_velocity_card_v1.yaml).
- Hàm tạo ID: [`src/pit_feature_store/entities.py`](../src/pit_feature_store/entities.py).
- Unit tests: [`tests/unit/test_entities.py`](../tests/unit/test_entities.py).
