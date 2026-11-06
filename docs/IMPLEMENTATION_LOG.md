# Nhật ký triển khai kỹ thuật

Tài liệu này giải thích chi tiết các phần **đã hoàn thành** của project
Point-in-Time Correct Feature Store. Đây là tài liệu đọc lại và vận hành; trạng thái
checklist ngắn gọn vẫn được quản lý tại
[`PROJECT_PROGRESS.md`](../PROJECT_PROGRESS.md).

## 1. Cách duy trì tài liệu

Sau khi hoàn thành một bước, cập nhật đồng thời:

1. Tick công việc và ghi bằng chứng trong `PROJECT_PROGRESS.md`.
2. Thêm hoặc cập nhật mục tương ứng trong file này.
3. Ghi rõ mục đích, input, xử lý, output, quality checks, cách chạy và cách đọc kết quả.
4. Chỉ ghi **đã hoàn thành** khi code đã chạy/test thành công; không mô tả kế hoạch như
   kết quả thực tế.
5. Nếu output nằm trong `.gitignore`, phải chỉ rõ cách tái tạo để máy khác có thể chạy lại.

Mẫu dùng cho các bước tiếp theo:

```text
Trạng thái và ngày hoàn thành
Mục đích
Input và giả định
Logic đã triển khai
Output và vị trí lưu
Quality checks / acceptance criteria
Cách tự chạy và theo dõi
Kết quả thực tế gần nhất
Giới hạn và quyết định quan trọng
Code, test và tài liệu liên quan
```

### Vì sao project phải làm theo thứ tự này?

Các bước tạo thành một chuỗi kiểm soát:

```text
Hiểu raw data
  → xác định key, time và lỗi nguồn có thể gặp
  → chọn surrogate entity có đủ lịch sử
  → lưu bản nguồn có lineage ở Bronze
  → chuẩn hóa thành Silver đáng tin cậy
  → mới định nghĩa và tính PIT features
```

- Nếu chưa profiling, ta có thể chọn một cột thiếu quá nhiều hoặc hiểu sai schema.
- Nếu chưa chốt entity, rolling features không biết phải gom lịch sử theo đối tượng nào.
- Nếu bỏ Bronze, rất khó truy ngược một giá trị Silver về file và dòng nguồn.
- Nếu bỏ Silver, feature engine phải lặp lại cast, join và null handling; mỗi nơi có thể
  xử lý khác nhau.
- Nếu tính feature trước khi chốt time/entity contract, kết quả có thể chạy được nhưng
  không chứng minh được PIT correctness hoặc khả năng tái tạo.

Vì vậy mỗi mốc tạo một contract đầu vào đáng tin cậy cho mốc tiếp theo.

## 2. Mốc 0 — Khởi tạo và chốt bài toán

**Trạng thái:** Hoàn thành.

### Mục đích

Xây một feature-store MVP có khả năng tạo historical features đúng tại thời điểm
quan sát, quản lý định nghĩa feature có version, tái tạo training dataset và hỗ trợ
backfill/rerun an toàn. IEEE-CIS Fraud Detection được dùng làm bộ dữ liệu kiểm chứng;
fraud detection là use case minh họa, không phải phạm vi duy nhất của platform.

### Kết quả

- Chốt đề tài Point-in-Time Correct Feature Store.
- Chốt lộ trình năm tuần và cấu trúc repository.
- Tạo môi trường Python, `pyproject.toml` và `.gitignore`.
- Tách raw/runtime data khỏi các tài liệu và source code được commit.

### Bằng chứng

- [`project_proposal.md`](project_proposal.md)
- [`DE_CUONG_DE_TAI_PIT_FEATURE_STORE.md`](DE_CUONG_DE_TAI_PIT_FEATURE_STORE.md)
- [`PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md`](../PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md)
- [`pyproject.toml`](../pyproject.toml)

## 3. Mốc 1 — Dataset inventory, profiling và data dictionary

**Trạng thái:** Hoàn thành.

### Mục đích

Hiểu cấu trúc và chất lượng nguồn trước khi thiết kế entity, event time hoặc feature.
Profiling ở bước này là audit kỹ thuật ban đầu, không thay thế toàn bộ EDA phục vụ mô
hình.

### Input

Bốn file CSV trong `data/raw/`:

- `train_transaction.csv`
- `train_identity.csv`
- `test_transaction.csv`
- `test_identity.csv`

### Logic đã triển khai

- Đọc header và metadata file.
- Đếm dòng, cột và dung lượng.
- Kiểm tra schema và `TransactionID`.
- Kiểm tra phân bố `isFraud`, identity coverage và phạm vi `TransactionDT`.
- Tính null rate và cardinality.
- Tính streaming SHA-256 cho từng raw file.
- Sinh JSON cho máy đọc và Markdown cho người review.

SHA-256 đại diện cho **nội dung byte của một raw file**. Chỉ cần nội dung file thay đổi,
checksum gần như chắc chắn thay đổi. Manifest vì vậy cho phép xác định chính xác phiên
bản input đã được dùng trong một run.

### Các metrics/checks và lý do sử dụng

| Metric/check | Cách hiểu | Vì sao cần trong project |
|---|---|---|
| File size | Số byte/MB của file nguồn | Phát hiện file tải thiếu hoặc thay đổi bất thường; ước lượng RAM, thời gian đọc và định dạng lưu phù hợp. |
| Row count | Tổng số bản ghi từng source | Là baseline để reconciliation: Bronze/Silver không được âm thầm mất hoặc nhân bản transaction. |
| Column count và schema | Tên/số cột của từng bảng | Phát hiện schema drift và xác nhận train/test có thể chuẩn hóa về cùng contract. |
| Null `TransactionID` | Số dòng không có khóa giao dịch | Dòng thiếu key không thể join identity, kiểm tra uniqueness hoặc truy vết ổn định. |
| Unique/duplicate `TransactionID` | Số ID khác nhau và số ID lặp | Xác nhận một ID đại diện một transaction; duplicate có thể làm join nhân bản và làm sai rolling count. |
| `TransactionDT` min/max | Offset thời gian nhỏ nhất/lớn nhất | Cho biết timeline và horizon khả dụng; là cơ sở tạo `event_time`, chronological split và rolling windows. |
| Monotonic `TransactionDT` | Dữ liệu nguồn có tăng theo thời gian hay không | Giúp hiểu source order, nhưng pipeline vẫn dùng điều kiện thời gian rõ ràng chứ không dựa vào thứ tự file. |
| Negative `TransactionDT` | Số offset âm | Offset âm có thể vi phạm synthetic timeline hoặc báo lỗi parse/nguồn. |
| `TransactionAmt` min/max và số âm | Miền giá trị amount | Phát hiện cast lỗi/outlier; amount âm cần diễn giải nghiệp vụ trước khi đưa vào rolling sum/average. |
| `isFraud` distribution/rate | Số và tỷ lệ hai nhãn | Xác nhận label hợp lệ và mức mất cân bằng; giúp chọn PR-AUC/Recall@FPR về sau. Không dùng label để tạo entity. |
| Identity coverage | `identity rows matched / transaction rows` | Chứng minh identity chỉ phủ một phần transaction, do đó bắt buộc dùng left join và cần `has_identity`. |
| Null rate mỗi cột | `null rows / total rows` | Đo mức sẵn có. Với entity candidate, null trực tiếp làm giảm coverage; với model, nó quyết định null handling. |
| Cardinality | Số giá trị khác nhau không null | Phân biệt cột categorical với ID/high-cardinality; phát hiện constant column và hỗ trợ đánh giá entity candidate. |
| Train/test schema diff | Cột chỉ có ở một split hoặc khác tên | Ngăn schema skew. Audit phát hiện identity test dùng `id-01` trong khi train dùng `id_01`, nên Silver phải chuẩn hóa. |
| SHA-256 | Hash nội dung byte của raw file | Xác định chính xác input version và phát hiện thay đổi dù tên file không đổi. |

Không có một null rate hay cardinality “tốt” chung cho mọi cột. Metric phải được đọc theo
vai trò: một cột null 90% có thể vẫn hữu ích cho model, nhưng là lựa chọn rất tệ nếu dùng
làm thành phần bắt buộc của entity key.

### Kết quả chính và ảnh hưởng tới thiết kế

- Train transaction có 590,540 dòng; test có 506,691 dòng.
- `TransactionID` không null, không duplicate trong bốn source.
- Fraud rate train là 3.4990%, cho thấy target mất cân bằng.
- Identity coverage chỉ 24.4239% ở train và 28.0066% ở test, nên không được inner join.
- `TransactionDT` train trải trên khoảng 182 ngày và là relative offset, không phải ngày thật.
- `addr1` null 11.1264% ở train, tạo trade-off khi chọn primary entity.
- Train/test transaction tương thích sau khi bỏ `isFraud`; identity khác quy ước dấu
  gạch và phải normalize ở Silver.

### Cách chạy và theo dõi

```powershell
python pipelines/profile_dataset.py
```

Chỉ tạo/kiểm tra checksum:

```powershell
python pipelines/profile_dataset.py --checksum-only
```

Đầu ra:

- `reports/generated/dataset_profile.json` — runtime artifact, không commit.
- `reports/generated/raw_checksums.json` — runtime artifact, không commit.
- [`dataset_audit_summary.md`](../reports/dataset_audit_summary.md) — báo cáo review.
- [`data_dictionary.md`](data_dictionary.md) — ý nghĩa và cách dùng các nhóm cột.

### Code và test liên quan

- [`profile_dataset.py`](../pipelines/profile_dataset.py)
- [`profiling.py`](../src/pit_feature_store/profiling.py)

## 4. Mốc 2 — Phân tích và chốt surrogate entities

**Trạng thái:** Hoàn thành.

### Mục đích

IEEE-CIS không cung cấp customer/account ID. Project cần surrogate entity để nhóm các
giao dịch có liên quan và tính velocity, recency, rolling count/amount. Entity chỉ là
khóa nghiên cứu, không được diễn giải là danh tính thật.

### Phân tích đã thực hiện

Với mỗi candidate, pipeline đo:

- assigned coverage và số entity duy nhất;
- mean/median/quantiles số transaction trên entity;
- singleton rate và repeat transaction coverage;
- top-entity skew;
- temporal span của repeated entities;
- label diagnostics chỉ để quan sát, không dùng `isFraud` tạo key.

Quy tắc phân tích là strict complete case và exact tuple match. Thiếu bất kỳ thành phần
nào thì candidate tương ứng không được gán entity.

### Các metrics, cách tính và lý do sử dụng

Ký hiệu `N` là tổng transaction, `N_assigned` là số transaction tạo được candidate key,
`E` là tập entity và `n_e` là số transaction của entity `e`.

#### Assigned transaction coverage

```text
assigned coverage = N_assigned / N
```

Metric trả lời bao nhiêu phần trăm transaction thực sự nhận được entity. Coverage thấp
nghĩa là nhiều observation không có rolling history theo view đó. Đây là chi phí trực
tiếp khi thêm thành phần vào key. `(card1, addr1)` có coverage 88.87%, vì 11.13% train
rows thiếu ít nhất một thành phần.

#### Unique entities

```text
unique entities = count(distinct candidate tuple trên assigned rows)
```

Quá ít entity có thể cho thấy key quá rộng và gom nhiều đối tượng khác nhau. Quá nhiều
entity có thể cho thấy key quá hẹp, làm lịch sử bị chia nhỏ. Metric này phải đọc cùng
coverage, transactions/entity và skew.

#### Transactions per entity

Với phân bố `{n_e}`, báo cáo mean, median, P95, P99 và maximum:

- Median mô tả entity điển hình và ít bị outlier chi phối.
- Mean cho mức lịch sử trung bình nhưng có thể bị vài entity lớn kéo lên.
- P95/P99 mô tả phần đuôi của phân bố.
- Maximum giúp tìm hotspot hoặc key quá rộng.

Rolling features chỉ có giá trị khi entity có đủ lịch sử. `card1_addr1` có median 2
transaction/entity, còn `card1` có median 4: primary cụ thể hơn nhưng lịch sử mỏng hơn.

#### Singleton entity rate

```text
singleton rate = count(entity có n_e = 1) / count(all entities)
```

Singleton không có giao dịch trước đó tại lần xuất hiện duy nhất, nên không tạo được
velocity, recency hay rolling aggregate có thông tin. Rate cao báo key phân mảnh lịch sử.
Vì nó đếm theo entity chứ không theo transaction, cần đọc thêm repeat coverage.

#### Repeat transaction coverage

```text
repeat coverage assigned = sum(n_e với n_e >= 2) / N_assigned
repeat coverage overall  = sum(n_e với n_e >= 2) / N
```

Đây là metric gần nhất với lợi ích thực tế: bao nhiêu transaction thuộc nhóm có cơ hội
sở hữu lịch sử. Hai mẫu số tách hai nguyên nhân mất coverage: không tạo được key và tạo
được key nhưng entity chỉ xuất hiện một lần.

#### Entity skew

```text
top-k share  = transaction thuộc k entity lớn nhất / N_assigned
top-1% share = transaction thuộc 1% entity lớn nhất / N_assigned
```

Skew cao có thể nghĩa key gom nhiều đối tượng không liên quan, đồng thời tạo hotspot tốn
bộ nhớ/thời gian. `card1` có top-1% share 52.97%, cao hơn `card1_addr1` là 39.96%; thêm
address giúp entity cụ thể hơn.

#### Temporal span của repeated entities

```text
span_e = max(TransactionDT của e) - min(TransactionDT của e)
```

Báo cáo P50/P90/P95/max của span. Entity lặp nhiều lần trong vài phút vẫn không hỗ trợ
tốt window 7/30 ngày. Span cho biết candidate có lịch sử đủ dài cho horizon dự kiến hay
không. Nó chưa chứng minh mọi observation đều có prior history.

#### Label diagnostics

Gồm fraud rate trên assigned rows, tỷ lệ entity có fraud, mixed-label entity và fraud
nằm trong repeated entities. Chúng giúp hiểu surrogate key có gom các transaction liên
quan theo labeling logic hay không. Label chỉ được xem **sau khi** tạo entity; đưa
`isFraud` vào công thức key sẽ gây target leakage.

### Vì sao không chọn bằng một metric duy nhất?

- Chỉ tối đa coverage sẽ ưu tiên `card1`, nhưng key có thể quá rộng và skew cao.
- Chỉ tối đa số entity sẽ ưu tiên key rất chi tiết, nhưng coverage/repeat history giảm.
- Chỉ tối thiểu singleton có thể bỏ qua null coverage và ý nghĩa nghiệp vụ.
- Chỉ nhìn fraud concentration có nguy cơ thiết kế key theo target.

Quyết định phải cân bằng availability, khả năng lặp lại, độ cụ thể, temporal span, chi
phí tính toán và tính hợp lý nghiệp vụ.

### Quyết định đã chốt

- Primary: `(card1, addr1)` → `card_address_entity_id`.
- Secondary: `card1` → `card_entity_id`.
- Khi có primary, model MVP vẫn nhận **cả hai** feature sets.
- Khi thiếu `addr1`, primary là null nhưng secondary vẫn có thể dùng được.
- ID được hash deterministic bằng SHA-256, có prefix và version riêng.
- `isFraud` tuyệt đối không tham gia công thức entity ID.

Primary `(card1, addr1)` được chọn vì cụ thể hơn `card1`, giảm concentration nhưng vẫn
có repeat coverage overall 86.36% và temporal span phù hợp window 1/7/30 ngày. Secondary
`card1` giữ coverage 100% và repeat coverage overall 99.42%, làm view bổ sung cho 11.13%
train rows thiếu primary. Hai view được giữ riêng để model tự học mức hữu ích, không trộn
lịch sử coarse và fine vào cùng một feature.

### Cách chạy

```powershell
python pipelines/analyze_entity_keys.py
```

Đầu ra:

- `reports/generated/entity_key_profile.json` — runtime artifact, không commit.
- [`entity_key_analysis.md`](../reports/entity_key_analysis.md)
- [`entity_key_decision.md`](entity_key_decision.md)

### Code, cấu hình và test liên quan

- [`entities.yaml`](../configs/entities.yaml)
- [`analyze_entity_keys.py`](../pipelines/analyze_entity_keys.py)
- [`entities.py`](../src/pit_feature_store/entities.py)
- [`test_entities.py`](../tests/unit/test_entities.py)

## 5. Mốc 3 — Bronze/Silver data foundation

**Trạng thái:** Hoàn thành ngày 2026-11-05.

Luồng dữ liệu hiện tại:

```text
Raw CSV
  → profiling/checksum
  → Bronze Parquet (source-preserving + lineage metadata)
  → Silver Parquet (canonical transaction dataset)
```

### 5.1. Source configuration và synthetic epoch

#### Mục đích

Đưa đường dẫn, loại bảng, split, key và required columns ra cấu hình thay vì hard-code.
Synthetic epoch tạo một timeline kỹ thuật ổn định từ `TransactionDT`, vì dataset không
cung cấp timestamp thật.

#### Quyết định

```text
synthetic_epoch = 2017-01-01T00:00:00Z
event_time = synthetic_epoch + TransactionDT seconds
```

Synthetic timestamp chỉ bảo toàn thứ tự và khoảng cách; không được tuyên bố là thời
điểm giao dịch thật. Đổi epoch là thay đổi data contract và yêu cầu rebuild Silver cùng
các output PIT phụ thuộc.

#### Vì sao cần cấu hình và epoch cố định?

- Source path trong config giúp cùng code chạy ở máy khác mà không sửa logic pipeline.
- Required columns làm pipeline fail sớm khi source contract bị phá vỡ.
- Split/table/key metadata giúp code phân biệt train/test và transaction/identity.
- Epoch cố định bảo đảm cùng `TransactionDT` luôn sinh cùng `event_time` qua mọi rerun.
- Timestamp giúp window SQL, cutoff, partition và backfill dễ biểu diễn.
- Epoch không thêm thông tin tương lai: nó chỉ dịch toàn bộ relative timeline bằng cùng
  một hằng số, nên thứ tự và khoảng cách giữa transaction không đổi.

#### Bằng chứng

- [`sources.yaml`](../configs/sources.yaml)
- [`data_contract.md`](data_contract.md)

### 5.2. Raw checksum manifest

#### Mục đích

Gắn mỗi lần xử lý với đúng nội dung raw input, phát hiện file bị thay đổi và hỗ trợ tái
lập/audit. Mỗi source có checksum riêng; file manifest là danh sách các checksum cùng
metadata của toàn bộ input tại lần kiểm tra đó.

#### Output

`reports/generated/raw_checksums.json` (local, không commit).

#### Metrics được lưu và cách đọc

- `sha256`: identity của nội dung file, dùng so sánh input version.
- File size: sanity check và phát hiện file truncate.
- Source/path: ánh xạ checksum về đúng logical source.

Checksum không chứng minh dữ liệu đúng nghiệp vụ; nó chỉ chứng minh hai nội dung file có
giống hệt nhau hay không. Vì vậy phải dùng cùng schema, row-count và quality checks.

### 5.3. Bronze ingestion

#### Mục đích

Chuyển raw CSV sang Parquet hiệu quả hơn nhưng vẫn giữ nguyên biểu diễn nguồn, đồng thời
thêm lineage để truy ngược từng dòng về file và ingestion run.

#### Logic

- Các cột nguồn được lưu dưới dạng UTF-8 string, chưa cast kiểu nghiệp vụ.
- Chuỗi rỗng vẫn là chuỗi rỗng.
- Thứ tự nguồn được ghi bằng `_source_row_number`, bắt đầu từ 1.
- Thêm sáu cột metadata:
  `_ingestion_run_id`, `_source_name`, `_source_file`,
  `_source_checksum_sha256`, `_ingested_at_utc`, `_source_row_number`.
- Ghi vào staging, validate row/schema/checksum rồi mới publish để tránh thay output tốt
  bằng một run lỗi.

#### Vì sao cần từng bước và metadata?

| Thành phần | Lý do |
|---|---|
| Giữ raw values dạng string | Bronze tái hiện nguồn; cast sai không được làm mất biểu diễn ban đầu. |
| Giữ empty string | Bảo toàn đúng nguồn trước khi Silver áp null policy. |
| `_ingestion_run_id` | Xác định run nào tạo snapshot. |
| `_source_name`, `_source_file` | Truy ngược logical source và file vật lý. |
| `_source_checksum_sha256` | Gắn từng dòng với đúng phiên bản raw content. |
| `_ingested_at_utc` | Biết dữ liệu được tiếp nhận khi nào; đây không phải event time. |
| `_source_row_number` | Truy đúng dòng nguồn và giữ stable lineage. |
| Staging → validate → publish | Run lỗi không ghi đè canonical Bronze đang tốt. |

#### Metrics và acceptance checks của Bronze

| Check | Vì sao cần |
|---|---|
| Raw row count = Bronze row count | Chứng minh ingestion không mất hoặc nhân bản dòng. |
| Bronze columns = source columns + 6 metadata | Chứng minh không mất cột và metadata được thêm đủ. |
| Computed SHA-256 = raw manifest SHA-256 | Ngăn ingest nhầm phiên bản file. |
| Required columns tồn tại | Ngăn downstream chạy trên schema không hợp lệ. |
| Đọc lại Parquet và reconciliation | Xác nhận output không chỉ ghi được mà còn đọc/đếm đúng. |
| 4/4 source status success | Xác nhận snapshot đầu vào cần thiết cho Silver đã sẵn sàng. |

#### Cách chạy và theo dõi

Smoke test source nhỏ:

```powershell
python pipelines/ingest_bronze.py --sources train_identity --progress-every-rows 50000
```

Full run:

```powershell
python pipelines/ingest_bronze.py --progress-every-rows 100000
```

Theo dõi `[progress]`, `[validated]` và chỉ coi thành công khi terminal có:

```text
[bronze] success: manifest=...
```

#### Output

- `data/bronze/<source>/data.parquet` — local, không commit.
- `reports/generated/bronze_ingestion_manifest.json` — local, không commit.

#### Kết quả full run gần nhất

| Source | Rows | Source columns | Bronze columns |
|---|---:|---:|---:|
| train_transaction | 590,540 | 394 | 400 |
| train_identity | 144,233 | 41 | 47 |
| test_transaction | 506,691 | 393 | 399 |
| test_identity | 141,907 | 41 | 47 |

Tổng cộng 1,383,371 dòng; 4/4 sources thành công và checksum khớp raw manifest.

#### Code và test

- [`ingest_bronze.py`](../pipelines/ingest_bronze.py)
- [`bronze.py`](../src/pit_feature_store/bronze.py)
- [`test_bronze.py`](../tests/unit/test_bronze.py)

### 5.4. Silver transformation

#### Mục đích

Tạo một canonical transaction dataset thống nhất cho feature computation: kiểu dữ liệu
đúng, timeline kỹ thuật, identity đã join, entity IDs và metadata định tuyến sẵn có.

#### Logic

1. Validate Bronze inputs và duplicate policy.
2. Chuẩn hóa tên/schema train-test và cast kiểu nghiệp vụ.
3. Chuyển chuỗi rỗng thành null tại Silver.
4. Với exact duplicate, giữ một bản. Nếu cùng `TransactionID` nhưng nội dung xung đột,
   pipeline fail vì không có dữ liệu nguồn đáng tin cậy để chọn bản đúng.
5. Tạo `event_time`, `event_date`, `event_month` và `dataset_split`.
6. Left join transaction với identity để không làm mất transaction; tạo `has_identity`.
7. Thêm `card_entity_id`, `card_address_entity_id`, availability/routing và entity version.
8. Thêm Silver run/schema metadata.
9. Ghi Parquet partition theo `dataset_split/event_month`.
10. Chạy quality checks và semantic fingerprint trước khi publish.

#### Vì sao cần từng bước?

- **Validate trước:** lỗi duplicate/schema dừng trước khi tốn chi phí build full data.
- **Cast tập trung ở Silver:** mọi downstream consumer dùng cùng kiểu, tránh nơi coi
  amount là string còn nơi khác coi là numeric.
- **Null normalization:** một missing value không bị biểu diễn lẫn lộn bởi `""`, `NULL`
  hoặc placeholder.
- **Duplicate policy:** exact copy không thêm thông tin; conflicting duplicate không thể
  chọn tùy tiện nên pipeline fail để bảo vệ tính tái tạo.
- **Left identity join:** identity coverage thấp; inner join sẽ làm mất phần lớn
  transactions và thay đổi population.
- **Entity IDs tạo một lần:** feature jobs dùng chung đúng công thức/version.
- **Partitioned Parquet:** giảm dữ liệu phải scan và hỗ trợ backfill theo thời gian.
- **Validate trước publish:** canonical output chỉ thay đổi khi toàn bộ checks pass.

#### Các trường Silver được tạo

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

Silver còn giữ lineage cần thiết từ Bronze và chứa các trường identity sau left join.
`isFraud` của test là null để train/test có schema canonical thống nhất.

#### Vì sao partition theo tháng

Output có cấu trúc:

```text
data/silver/transactions/
  dataset_split=train/event_month=YYYY-MM/*.parquet
  dataset_split=test/event_month=YYYY-MM/*.parquet
```

Partition tháng đủ nhỏ để DuckDB bỏ qua các tháng không cần đọc (partition pruning),
nhưng không nhỏ đến mức tạo hàng trăm/nghìn file theo ngày hoặc giờ. Nó cũng giúp quản
lý backfill theo khoảng thời gian. Partition không tự sắp xếp dữ liệu và không tự đảm
bảo PIT correctness.

#### Data-quality checks

- Row count theo split bằng transaction input sau duplicate policy.
- `TransactionID` không null và duy nhất trong mỗi split.
- `TransactionDT`, `TransactionAmt` và train label cast hợp lệ.
- `event_time` không null và đúng công thức.
- Left join không làm mất hoặc nhân bản transaction.
- Identity match count và `has_identity` nhất quán.
- Entity availability/routing nhất quán với null policy.
- Semantic fingerprint ổn định giữa các lần chạy cùng business data/lineage.

Fingerprint cố ý loại các metadata thay đổi theo từng run như run ID và created time.
Nếu không loại, rerun đúng logic vẫn bị báo khác chỉ vì thời điểm chạy khác nhau.

#### Ý nghĩa và lý do của từng Silver metric

| Metric/check | Điều kiện mong đợi | Lý do |
|---|---|---|
| `row_count_by_split` | Bằng transaction rows sau dedup | Bắt lỗi mất/nhân bản dòng do join hoặc filter. |
| Null `TransactionID` | 0 | Transaction không key không thể định danh và kiểm tra uniqueness. |
| Unique `TransactionID` | Một ID/split | Bảo đảm grain Silver vẫn là một dòng trên transaction. |
| Duplicate excess rows | 0 sau policy | Xác nhận dedup đã tạo canonical grain. |
| Conflicting duplicate keys | 0; lớn hơn thì fail | Không đủ cơ sở chọn một trong các bản ghi mâu thuẫn. |
| Invalid `TransactionDT` | 0 | Không tạo được event time đáng tin cậy nếu offset cast lỗi. |
| Null/incorrect `event_time` | 0 | PIT windows và chronological split phụ thuộc trực tiếp vào time. |
| Invalid `TransactionAmt` | 0 | Rolling sum/mean sẽ sai hoặc không tính được nếu cast lỗi. |
| Invalid train label | 0 | Bảo vệ training/evaluation; test label được phép null. |
| `identity_matches_by_split` | Khớp identity join keys | Bắt lỗi join condition, normalize column hoặc duplicate identity. |
| `has_identity` consistency | True đúng khi match tồn tại | Phân biệt missing identity hợp lệ với lỗi join. |
| Null `card_entity_id` | Theo null policy; hiện 0 | Secondary coverage phải đúng với phân tích candidate. |
| Null `card_address_entity_id` | Khớp thiếu `card1/addr1`; hiện 131,315 | Kiểm tra primary availability/routing, không tự điền entity sai. |
| Event-time min/max | Nằm trong synthetic timeline dự kiến | Phát hiện sai đơn vị giây/millisecond hoặc sai epoch. |
| Parquet file count/size | Không thiếu output hoặc bùng nổ small files | Theo dõi layout/chi phí scan; không phải metric correctness độc lập. |
| Semantic fingerprint | Rerun cùng business data cho cùng fingerprint | Chứng minh deterministic logic, bỏ qua metadata động. |
| `matches_previous_run` | `true` khi input/config/logic không đổi | Acceptance signal cho deterministic rerun. |

Fingerprint không nhằm chứng minh hai file Parquet giống từng byte: codec, file order hoặc
metadata vật lý có thể khác. Nó so sánh business values và stable lineage ở mức semantic.

#### Tại sao cần cả unit tests và full-data checks?

- Unit tests kiểm tra từng quy tắc bằng fixtures nhỏ, kể cả edge case không xuất hiện
  trong dataset hiện tại như conflicting duplicate.
- Full-data checks chứng minh quy tắc đúng với 1,097,231 transaction thật.
- Ruff kiểm tra lỗi/style tĩnh; `git diff --check` kiểm tra whitespace thay đổi.

Các lớp kiểm tra không thay thế nhau: code có thể pass unit test nhưng lỗi schema/hết RAM
trên dữ liệu thật; full run có thể pass nhưng chưa bao phủ một edge case tương lai.

#### Cách chạy và theo dõi

```powershell
python pipelines/build_silver.py --memory-limit 4GB
```

Máy ít RAM:

```powershell
python pipelines/build_silver.py --memory-limit 2GB --threads 2
```

Theo dõi sáu stage từ validation đến publish. Stage ghi Parquet có thể im lặng khoảng
một phút. Chỉ coi thành công khi có:

```text
[6/6] success: manifest=...
```

Xem manifest và partition:

```powershell
Get-Content reports/generated/silver_build_manifest.json
Get-ChildItem data/silver/transactions -Recurse -Filter *.parquet
```

#### Kết quả full run gần nhất

- Train: 590,540 transactions.
- Test: 506,691 transactions.
- Tổng: 1,097,231 transactions.
- Identity matches: train 144,233; test 141,907.
- 14 Parquet files/partitions, tổng dung lượng 110,559,986 bytes.
- Event-time range: `2017-01-02T00:00:00Z` đến `2018-01-31T23:59:05Z`.
- Null `TransactionID`: 0; null `event_time`: 0.
- Conflicting duplicate keys: 0 ở cả bốn source.
- Null primary card-address entity: 131,315; secondary card entity không null.
- Hai full runs liên tiếp có cùng fingerprint:
  `rows=1097231;xor64=1668359128455216076`.
- Manifest gần nhất có `matches_previous_run: true`.

#### Cách xem Silver data

DuckDB query trực tiếp Parquet, không cần chạy database server:

```python
import duckdb

duckdb.sql("""
    SELECT dataset_split, event_month, COUNT(*) AS row_count
    FROM read_parquet(
        'data/silver/transactions/**/*.parquet',
        hive_partitioning = true
    )
    GROUP BY 1, 2
    ORDER BY 1, 2
""").show()
```

Trong kiến trúc hiện tại, Parquet là nơi lưu Silver data; DuckDB là query/processing
engine đọc trực tiếp các file đó.

#### Code và test

- [`build_silver.py`](../pipelines/build_silver.py)
- [`silver.py`](../src/pit_feature_store/silver.py)
- [`test_silver.py`](../tests/unit/test_silver.py)

### 5.5. Cách chạy bộ kiểm tra code hiện tại

```powershell
pytest
ruff check .
git diff --check
```

Chỉ kiểm tra Silver:

```powershell
pytest tests/unit/test_silver.py -v
```

`pytest`/Ruff kiểm tra code và test fixtures; full-data Silver build mới chứng minh pipeline
chạy được trên toàn bộ local dataset. Hai loại bằng chứng bổ sung cho nhau, không thay thế
nhau.

## 6. Mốc 4 — Feature Registry và golden dataset

**Trạng thái:** Đang thực hiện.

### 6.1. PIT cutoff và same-timestamp policy

**Trạng thái:** Hoàn thành ngày 2026-11-06.

#### Tại sao cần chốt rule này trước khi viết engine?

`event_time` của IEEE-CIS có độ phân giải theo giây, nên nhiều transaction có thể cùng
timestamp. Nếu không có contract rõ ràng:

- Kết quả có thể phụ thuộc physical row/file order.
- Current transaction có thể tự đi vào count/sum của chính nó.
- Hai implementation SQL khác nhau có thể tạo feature khác nhau.
- Rerun/backfill có thể không deterministic.
- Golden dataset không có một expected answer duy nhất.

#### Rule đã chốt

Observation và history được sắp xếp bằng tuple:

```text
(event_time ASC, TransactionID ASC)
```

History `h` hợp lệ cho observation `o` khi cùng entity và:

```text
h.event_time < o.event_time
OR (h.event_time = o.event_time AND h.TransactionID < o.TransactionID)
```

Tương đương:

```text
(h.event_time, h.TransactionID) < (o.event_time, o.TransactionID)
```

Hệ quả:

- Current event bị loại vì tuple bằng observation, không phải nhỏ hơn.
- Cùng timestamp, ID nhỏ hơn được dùng; ID lớn hơn bị loại.
- Future timestamp luôn bị loại.
- Biên bắt đầu window `observation_time - W` được tính (inclusive).
- Cutoff observation là exclusive theo tuple.
- Kết quả không phụ thuộc thứ tự vật lý trong Parquet.

#### Ví dụ

Với cùng entity và cùng `event_time = 10:00:00`:

| Observation ID | Same-time history hợp lệ |
|---:|---|
| 101 | Không có |
| 102 | 101 |
| 103 | 101, 102 |

Nếu amount lần lượt là 10, 20 và 30 thì historical sum tương ứng là 0, 10 và 30;
observation không tự cộng amount của chính nó.

#### Vì sao dùng `TransactionID`?

Nó là unique key sẵn có và tạo total order ổn định khi `event_time` bằng nhau. Đây là
tie-breaker kỹ thuật/modeling assumption, không phải khẳng định ID là timestamp. Khi áp
dụng production, chỉ dùng policy này nếu source xác nhận ID/sequence phản ánh thứ tự;
nếu không phải dùng same-time batch semantics để các event cùng timestamp không thấy nhau.

Late-arriving row có tuple nhỏ hơn observation đã materialize có thể làm feature quá khứ
thay đổi. Trường hợp đó cần backfill/version; muốn tái hiện chính xác dữ liệu đã biết tại
processing time thì phải bổ sung `ingestion_time` và bitemporal cutoff.

#### Config và tài liệu

- [`transaction_velocity_v1.yaml`](../configs/features/transaction_velocity_v1.yaml)
- [`transaction_velocity_card_v1.yaml`](../configs/features/transaction_velocity_card_v1.yaml)
- [`pit_time_policy.md`](pit_time_policy.md)
- [`data_contract.md`](data_contract.md)

### 6.2. Các bước Mốc 4 còn lại

#### MVP feature selection v1

**Trạng thái:** Hoàn thành ngày 2026-11-06.

Project chốt 10 logical features và tính độc lập cho hai entity views. Vì mỗi view có
prefix riêng, model nhận 20 output columns chứ không trộn coarse card history với
fine-grained card-address history.

Hai view tạo ra các cặp feature có cùng công thức nhưng khác phạm vi entity:

```text
card_addr_* → lịch sử theo (card1, addr1), cụ thể hơn
card_*      → lịch sử theo card1, rộng hơn và coverage cao hơn
```

Ví dụ một logical feature `txn_count_24h` tạo thành:

```text
card_addr_txn_count_24h
card_txn_count_24h
```

Model nhận cả hai để tự học lịch sử cụ thể và lịch sử rộng; pipeline không ghi giá trị
secondary vào cột primary.

##### 1. `txn_count_1h`

Đếm eligible historical transactions trong một giờ trước observation. Feature này bắt
burst rất ngắn hạn như thử thẻ liên tục, bot giao dịch hoặc chia nhỏ giao dịch trong vài
phút. Hai entity cùng có 10 giao dịch trong tuần nhưng một entity thực hiện cả 10 trong
20 phút có mức velocity hoàn toàn khác.

##### 2. `txn_count_24h`

Đếm history trong 24 giờ. Window một giờ có thể bỏ sót hành vi được giãn ra nhiều giờ;
24 giờ mô tả mức hoạt động trong ngày và giúp nhận biết entity vẫn giao dịch dày dù không
có burst ngay sát observation.

##### 3. `txn_count_7d`

Đếm history trong bảy ngày, tạo baseline rộng hơn cho tần suất gần đây. Khi đọc cùng
`txn_count_1h` và `txn_count_24h`, model có thể nhận ra hoạt động của cả tuần vừa dồn vào
thời gian rất ngắn:

```text
txn_count_1h  = 5
txn_count_24h = 6
txn_count_7d  = 7
```

##### 4. `amount_sum_1h`

Tổng `TransactionAmt` lịch sử trong một giờ. Count giống nhau không đồng nghĩa exposure
giống nhau: năm giao dịch 5 USD khác hẳn năm giao dịch 500 USD. Feature này đo tốc độ
tích lũy giá trị trong thời gian rất ngắn.

##### 5. `amount_sum_24h`

Tổng amount trong 24 giờ. Nó phát hiện tổng exposure trong ngày ngay cả khi giao dịch
được giãn ra để `amount_sum_1h` không cao. Kết hợp với `txn_count_24h` giúp phân biệt
nhiều giao dịch nhỏ với ít giao dịch lớn.

##### 6. `amount_sum_7d`

Tổng amount trong bảy ngày. Feature này đo exposure tích lũy nhiều ngày và giúp so sánh
hoạt động rất gần với hoạt động cả tuần. Ví dụ `amount_sum_24h` gần bằng
`amount_sum_7d` cho thấy phần lớn giá trị tuần vừa tập trung trong một ngày.

##### 7. `amount_avg_24h`

Trung bình các `TransactionAmt` lịch sử hợp lệ trong 24 giờ. Hai entity có cùng tổng
amount có thể khác nhau vì một bên có nhiều giao dịch nhỏ, bên còn lại có ít giao dịch
lớn. Average bổ sung kích thước giao dịch điển hình gần đây.

Feature này có liên hệ toán học với sum và count, nhưng được giữ trong MVP để:

- cung cấp giá trị trực tiếp cho baseline model;
- kiểm thử aggregation `avg` và null handling;
- không giả định model sẽ tự học chính xác phép chia từ hai feature khác.

##### 8. `amount_max_7d`

Giá trị `TransactionAmt` lịch sử lớn nhất trong bảy ngày. Sum và average có thể che một
extreme event; maximum cho biết entity gần đây đã từng có giao dịch lớn đến mức nào.
Feature này không được đọc riêng vì một outlier hợp lệ có thể giữ maximum cao suốt cả
window.

##### 9. `seconds_since_previous_txn`

Số giây từ observation tới eligible historical transaction gần nhất. Count một giờ bằng
1 có thể có nghĩa giao dịch trước cách 10 giây hoặc 59 phút; recency phân biệt hai tình
huống đó và hữu ích cho card testing/automation.

Feature không bị giới hạn bởi window bảy ngày: nó tìm prior event gần nhất trong history
hợp lệ. Nếu không có prior event thì trả null, thể hiện “chưa có lịch sử” chứ không phải
0 giây.

##### 10. `distinct_product_count_7d`

Đếm số `ProductCD` khác nhau trong history bảy ngày. Count và amount đo cường độ nhưng
không đo độ đa dạng hành vi; entity có 10 giao dịch cùng một code khác entity có 10 giao
dịch trải trên nhiều code. Feature này đồng thời chứng minh registry/engine hỗ trợ
`count_distinct`, không chỉ numeric aggregates.

`ProductCD` chỉ có các code đã ẩn nghĩa nên project chỉ diễn giải đây là độ đa dạng mã,
không tự gán tên sản phẩm/dịch vụ cho từng code.

##### Vì sao chọn các window 1 giờ, 24 giờ và 7 ngày?

```text
1 giờ  → burst tức thời
24 giờ → hành vi trong ngày
7 ngày → baseline ngắn hạn nhiều ngày
```

Ba horizon giúp model nhìn cùng một hành vi ở nhiều độ rộng mà MVP vẫn đủ nhỏ để tính
expected result bằng tay. Training dataset vẫn kéo dài nhiều tháng; window bảy ngày chỉ
là lượng history dùng cho một số feature tại từng observation, không phải toàn bộ dữ
liệu dùng để train.

Window 30 ngày là extension hợp lý nhưng chưa bắt buộc trong v1. Chỉ bổ sung sau khi
pipeline 10 feature chạy end-to-end và benchmark cho thấy cần baseline dài hơn, để không
mở rộng test/backfill/documentation quá mức trong thời hạn năm tuần.

##### Cách các feature bổ sung cho nhau

| Câu hỏi | Feature trả lời |
|---|---|
| Giao dịch có diễn ra dồn dập không? | `txn_count_*` |
| Tổng exposure gần đây bao nhiêu? | `amount_sum_*` |
| Kích thước giao dịch điển hình thế nào? | `amount_avg_24h` |
| Gần đây từng có extreme amount không? | `amount_max_7d` |
| Prior transaction gần đến mức nào? | `seconds_since_previous_txn` |
| Hành vi trải trên bao nhiêu product code? | `distinct_product_count_7d` |

Không một feature đơn lẻ kết luận giao dịch là fraud. Model học sự kết hợp giữa current
transaction attributes và historical behavior, ví dụ count/sum cao, recency rất ngắn và
product diversity tăng.

##### Null và no-history semantics

- Entity hợp lệ nhưng không có history: count/sum/distinct bằng 0.
- Entity hợp lệ nhưng không tính được average/max/recency: trả null.
- Entity ID của view bị null: toàn bộ view trả null.
- Null `TransactionAmt` bị sum/average/max bỏ qua nhưng row vẫn thuộc transaction count.
- Null `ProductCD` không tham gia distinct count.
- Không feature nào dùng `isFraud`, tránh label leakage.

Phân biệt này cho model biết:

```text
0    → resolve được entity nhưng không có event/value trong window
null → không resolve được entity hoặc metric chưa thể tính
```

Definitions:

- [`transaction_velocity_v1.yaml`](../configs/features/transaction_velocity_v1.yaml)
- [`transaction_velocity_card_v1.yaml`](../configs/features/transaction_velocity_card_v1.yaml)

#### Các bước còn lại

1. Viết schema và validator cho Feature Registry.
2. Viết feature catalog.
3. Tạo golden dataset nhỏ và expected PIT outputs tính bằng tay.

Sau mỗi bước, bổ sung vào tài liệu này khi code/test hoặc quyết định tương ứng đã được
xác nhận.
