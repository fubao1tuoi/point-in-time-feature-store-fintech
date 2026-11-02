# Project Outline — Point-in-Time Correct Feature Store với IEEE-CIS Fraud Detection

> Tài liệu theo dõi phạm vi, các bước triển khai và tiêu chí hoàn thành cho đề tài **Point-in-Time Correct Feature Store** sử dụng bộ dữ liệu **IEEE-CIS Fraud Detection**.

## 1. Mục tiêu dự án

Xây dựng một Feature Store thu nhỏ có khả năng:

1. Nạp và chuẩn hóa dữ liệu giao dịch IEEE-CIS.
2. Tạo feature lịch sử cho từng giao dịch mà không sử dụng thông tin tương lai.
3. Sinh training dataset bằng Point-in-Time Join.
4. Materialize feature vào offline store và online store.
5. Hỗ trợ backfill, versioning, lineage và kiểm tra chất lượng dữ liệu.
6. Chứng minh training-serving consistency.
7. Tối ưu pipeline bằng partition pruning, semi-join reduction và computation reuse theo paper FeathrPO.
8. Dùng một mô hình fraud detection đơn giản để chứng minh feature tạo ra có thể sử dụng được.

Mục tiêu chính của dự án là **Data Engineering và Feature Platform**, không phải tối đa điểm Kaggle.

---

## 2. Câu hỏi dự án cần trả lời

Khi kết thúc, project phải trả lời được các câu hỏi sau:

- Làm thế nào tạo feature cho một giao dịch chỉ từ dữ liệu đã tồn tại trước giao dịch đó?
- Làm thế nào phát hiện và ngăn future leakage trong training dataset?
- Làm thế nào định nghĩa feature một lần nhưng sử dụng nhất quán khi training và serving?
- Làm thế nào chạy lại hoặc backfill feature cho một khoảng thời gian lịch sử?
- Làm thế nào biết feature được tạo từ nguồn nào, phiên bản logic nào và thời điểm nào?
- Làm thế nào giảm lượng dữ liệu phải scan khi tính các rolling-window feature?
- Làm thế nào kiểm chứng rằng tối ưu không làm thay đổi kết quả?

---

## 3. Đặc điểm dataset cần biết trước khi thiết kế

Nguồn chính thức: <https://www.kaggle.com/competitions/ieee-fraud-detection/data>

### 3.1. Các file

| File | Vai trò |
|---|---|
| `train_transaction.csv` | Giao dịch huấn luyện và nhãn `isFraud`. |
| `train_identity.csv` | Thông tin identity/device cho một phần giao dịch train. |
| `test_transaction.csv` | Giao dịch Kaggle test, không có nhãn công khai. |
| `test_identity.csv` | Identity/device cho một phần giao dịch test. |
| `sample_submission.csv` | Định dạng submission của Kaggle. |

Hai bảng transaction và identity được nối bằng `TransactionID`. Không phải giao dịch nào cũng có identity record, vì vậy phải dùng **left join** nếu cần giữ toàn bộ giao dịch.

### 3.2. Quy mô và phân bố nhãn

Training transaction có khoảng 590.540 dòng; trong đó khoảng 20.663 fraud, tương đương gần 3,5%. Đây là dữ liệu mất cân bằng mạnh.

Không dùng accuracy làm metric chính. Các metric phù hợp hơn:

- ROC-AUC để đối chiếu với metric Kaggle.
- PR-AUC vì positive class hiếm.
- Recall tại một mức false-positive rate cố định.
- Precision@K hoặc fraud capture rate trong top K cảnh báo.

### 3.3. Nhóm cột chính

- `TransactionID`: khóa giao dịch.
- `TransactionDT`: số giây lệch từ một mốc tham chiếu không được công bố.
- `TransactionAmt`: số tiền.
- `ProductCD`: nhóm sản phẩm.
- `card1`–`card6`: thuộc tính thẻ đã được mã hóa.
- `addr1`, `addr2`: thông tin địa chỉ đã mã hóa.
- `dist1`, `dist2`: biến khoảng cách.
- `P_emaildomain`, `R_emaildomain`: email domain.
- `C1`–`C14`, `D1`–`D15`, `M1`–`M9`, `V1`–`V339`: các nhóm feature, phần lớn đã được ẩn nghĩa hoặc engineered.
- `id_01`–`id_38`, `DeviceType`, `DeviceInfo`: identity/device information.
- `isFraud`: nhãn train.

### 3.4. Hạn chế ảnh hưởng trực tiếp đến đề tài

#### Không có timestamp lịch thật

`TransactionDT` là timedelta, không phải ngày giờ thật. Trong project, cần tạo:

```text
event_time = synthetic_epoch + TransactionDT seconds
```

Ví dụ dùng một mốc cố định giả lập như `2017-01-01 00:00:00 UTC`. Mốc này chỉ giúp hệ thống xử lý timestamp thuận tiện; không được diễn giải thành thời gian thật của giao dịch.

#### Không có customer ID rõ ràng

Dataset không cung cấp khóa khách hàng chính thức. Project cần tạo **surrogate entity key** từ một tổ hợp thuộc tính đã mã hóa, chẳng hạn:

```text
card_entity = hash(card1, card2, card3, card4, card5, card6, addr1)
```

Đây chỉ là khóa phân nhóm phục vụ demo, không được gọi là danh tính khách hàng thật. Cần thử một vài phiên bản key và đo:

- Tỷ lệ null.
- Số entity duy nhất.
- Số giao dịch trung bình/entity.
- Tỷ lệ singleton entity.
- Mức độ skew của entity lớn.

#### Nhiều feature đã được engineered và ẩn nghĩa

Để chứng minh Feature Store rõ ràng, MVP nên ưu tiên tạo feature mới từ các trường dễ hiểu như `TransactionAmt`, `TransactionDT`, `ProductCD`, card/address/email/device. Không nên lấy toàn bộ `V1`–`V339` làm trọng tâm giải thích.

#### Kaggle test không có nhãn công khai

Đánh giá model và pipeline phải dùng **chronological split từ train set**. Kaggle test chỉ dùng cho bước submission tùy chọn.

---

## 4. Phạm vi MVP và phạm vi nâng cao

### 4.1. MVP bắt buộc

- Raw ingestion từ bốn file CSV.
- Chuẩn hóa và lưu Parquet hoặc Delta.
- Left join transaction với identity bằng `TransactionID`.
- Tạo event time giả lập từ `TransactionDT`.
- Tạo ít nhất một surrogate entity key.
- Feature definitions có version.
- Batch Point-in-Time feature computation.
- Offline feature store.
- Chronological train/validation/test split.
- Automated leakage tests.
- Baseline fraud model.
- Metadata, data quality report và reproducible pipeline.

### 4.2. Phạm vi nên làm nếu còn thời gian trong 5 tuần

- Backfill theo khoảng thời gian.
- Partition pruning benchmark.
- Pipeline orchestration.
- Monitoring freshness và job health.
- Online store bằng Redis hoặc một key-value store tương đương.
- Feature serving API và training-serving consistency test.

### 4.3. Phạm vi nâng cao — không cam kết trong kế hoạch 5 tuần

- Semi-join reduction theo min/max label time.
- Reuse materialized windows, ví dụ `amount_30d` để tính `amount_60d`.
- Cost estimation dựa trên bytes hoặc partitions scanned.
- Tự động chọn partition granularity.
- Streaming simulation/replay theo `TransactionDT`.
- Feature drift và data-quality dashboard.
- Kaggle submission.

### 4.4. Không thuộc phạm vi chính

- Xây mô hình deep learning phức tạp.
- Tối ưu leaderboard Kaggle bằng ensemble lớn.
- Suy luận danh tính khách hàng thật.
- Triển khai hệ thống production chịu tải thực tế.
- Khẳng định surrogate entity là account/customer chính xác.

---

## 5. Kiến trúc mục tiêu

```text
Kaggle CSV
    │
    ▼
Raw/Bronze Layer
    │  schema validation + immutable copy
    ▼
Clean/Silver Layer
    │  type casting + event_time + dedup + left identity join
    ▼
Canonical Transaction Events
    │
    ├──────────────> Feature Registry / Definitions
    │                         │
    ▼                         ▼
Point-in-Time Compute Engine / Spark SQL
    │
    ├──────────────> Offline Feature Store (Parquet/Delta)
    │                         │
    │                         ▼
    │                 Training Dataset Builder
    │                         │
    │                         ▼
    │                 Baseline Fraud Model
    │
    └──────────────> Online Store (Redis, optional for MVP)
                              │
                              ▼
                       Feature Serving API

Across all layers: quality checks · lineage · versioning · metrics · orchestration
```

---

## 6. Cấu trúc repository đề xuất

```text
Fintech project/
├── README.md
├── PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md
├── LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md
├── configs/
│   ├── project.yaml
│   ├── sources.yaml
│   └── features/
│       ├── transaction_velocity_v1.yaml
│       └── transaction_amount_v1.yaml
├── data/
│   ├── raw/                 # Không commit CSV lớn
│   ├── bronze/
│   ├── silver/
│   ├── offline_store/
│   └── samples/
├── notebooks/
│   ├── 01_dataset_audit.ipynb
│   ├── 02_entity_key_analysis.ipynb
│   └── 03_feature_validation.ipynb
├── src/
│   ├── ingestion/
│   ├── transformations/
│   ├── entities/
│   ├── feature_store/
│   ├── training/
│   ├── serving/
│   └── monitoring/
├── pipelines/
│   ├── ingest.py
│   ├── build_silver.py
│   ├── materialize_features.py
│   ├── build_training_dataset.py
│   └── backfill.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── data_quality/
│   └── point_in_time/
├── sql/
│   ├── pit_join.sql
│   └── quality_checks.sql
├── docker/
├── reports/
│   ├── dataset_profile/
│   ├── benchmarks/
│   └── figures/
├── models/
└── docs/
    ├── architecture.md
    ├── feature_catalog.md
    ├── data_contract.md
    └── runbook.md
```

Các thư mục output lớn cần được thêm vào `.gitignore`. Chỉ commit sample nhỏ và metadata cần thiết.

---

## 7. Kế hoạch triển khai chi tiết

## Phase 0 — Chốt yêu cầu và tiêu chí thành công

### Công việc

- [ ] Viết problem statement một đoạn ngắn.
- [ ] Chốt use case: tạo feature lịch sử cho fraud scoring tại thời điểm giao dịch.
- [ ] Chốt ưu tiên: correctness → reproducibility → serving consistency → performance.
- [ ] Chọn tech stack ban đầu.
- [ ] Chốt phạm vi MVP và các phần nâng cao.
- [ ] Định nghĩa tiêu chí nghiệm thu cho từng phase.

### Tech stack gợi ý

| Nhu cầu | Lựa chọn ưu tiên | Lựa chọn nhẹ hơn |
|---|---|---|
| Data processing | PySpark | DuckDB/Polars |
| Offline format | Delta Lake hoặc Parquet | Parquet |
| Online store | Redis | SQLite/DuckDB demo |
| Orchestration | Prefect hoặc Airflow | Makefile/scripts |
| Data quality | Great Expectations/Pandera | Pytest + SQL assertions |
| Model | LightGBM/CatBoost | Logistic Regression |
| Experiment tracking | MLflow | JSON/CSV report |
| Serving | FastAPI | Python CLI |

### Đầu ra

- `README.md` có problem statement, kiến trúc sơ bộ và cách chạy.
- File cấu hình project.
- Danh sách acceptance criteria.

### Hoàn thành khi

- Người khác có thể đọc README và hiểu project xây gì, vì sao cần PIT correctness và phần nào không thuộc phạm vi.

---

## Phase 1 — Thu thập và kiểm kê dữ liệu

### Công việc

- [ ] Tải dataset bằng Kaggle CLI/API sau khi chấp nhận điều khoản competition.
- [ ] Không commit file gốc vào Git.
- [ ] Tính checksum cho từng file để bảo đảm reproducibility.
- [ ] Ghi lại số dòng, số cột, dung lượng và schema.
- [ ] Kiểm tra uniqueness của `TransactionID`.
- [ ] Kiểm tra coverage của identity table.
- [ ] Kiểm tra min/max và monotonicity của `TransactionDT`.
- [ ] Kiểm tra phân bố `isFraud` theo thời gian.
- [ ] Kiểm tra null rate, cardinality và memory usage theo cột.
- [ ] Phân nhóm cột theo transaction/card/address/email/count/delta/match/V/identity/device.

### Không nên làm

- Không random split dữ liệu ở phase này.
- Không fill missing toàn cục trước khi chia thời gian.
- Không dùng Kaggle test để tuning model.

### Đầu ra

- `reports/dataset_profile/dataset_inventory.md`.
- Machine-readable profile dạng JSON/Parquet.
- Data dictionary cho các nhóm cột đã biết.
- Checksum manifest.

### Hoàn thành khi

- Số dòng/cột khớp với nguồn.
- `TransactionID` join được đúng giữa transaction và identity.
- Các hạn chế của `TransactionDT`, missing identity và feature ẩn nghĩa được ghi rõ.

---

## Phase 2 — Xây Bronze và Silver data layers

### Bronze layer

- [ ] Copy hoặc convert dữ liệu gốc sang định dạng lưu trữ đã chọn.
- [ ] Giữ nguyên giá trị nguồn.
- [ ] Bổ sung metadata: `source_file`, `ingested_at`, `source_checksum`.
- [ ] Partition hợp lý; không partition theo cột có cardinality quá cao.

### Silver layer

- [ ] Cast kiểu dữ liệu nhất quán.
- [ ] Kiểm tra và loại duplicate `TransactionID` nếu có, đồng thời lưu quarantine record.
- [ ] Tạo `event_time` từ synthetic epoch và `TransactionDT`.
- [ ] Left join identity vào transaction.
- [ ] Tạo `has_identity`.
- [ ] Chuẩn hóa categorical missing thành một quy ước rõ ràng.
- [ ] Không impute thống kê bằng dữ liệu tương lai.
- [ ] Partition theo `event_date` hoặc một granularity được benchmark.
- [ ] Tạo schema contract cho canonical transaction event.

### Data contract tối thiểu

```text
TransactionID       non-null, unique
TransactionDT       non-null, >= 0
event_time          non-null, derived deterministically
TransactionAmt      numeric, >= 0
isFraud             {0,1} ở train; absent ở Kaggle test
identity columns    nullable
```

### Đầu ra

- Bronze và Silver datasets.
- `docs/data_contract.md`.
- Báo cáo data-quality pass/fail.

### Hoàn thành khi

- Chạy pipeline hai lần cho kết quả giống nhau.
- Không mất transaction khi left join identity.
- Có test chứng minh `event_time` tăng đúng theo `TransactionDT`.

---

## Phase 3 — Thiết kế entity key

Đây là phase quan trọng vì dataset không cung cấp customer ID thật.

### Candidate keys

- [ ] `card1`.
- [ ] `card1 + addr1`.
- [ ] `card1 + card2 + card3 + card5 + addr1`.
- [ ] Một tổ hợp card/address/email ổn định hơn sau khi profiling.
- [ ] Device key từ `DeviceInfo` hoặc identity fields cho subset có identity.

### Công việc

- [ ] Chuẩn hóa null trước khi hash.
- [ ] Tạo hash deterministic, không phụ thuộc thứ tự chạy.
- [ ] Đo số entity, transactions/entity, singleton rate và skew.
- [ ] Kiểm tra collision logic ở mức input string.
- [ ] Kiểm tra key có chứa cột có khả năng thay đổi theo thời gian hay không.
- [ ] Chọn một primary entity key cho MVP.
- [ ] Có thể giữ thêm secondary entity như device để tạo feature riêng.
- [ ] Viết decision record giải thích lý do chọn.

### Nguyên tắc

- Không dùng `isFraud` để tạo entity key.
- Không dùng thông tin tương lai để sửa entity key của quá khứ.
- Không gọi surrogate key là “customer identity chính xác”.

### Đầu ra

- `docs/entity_key_decision.md`.
- Module tạo entity key.
- Unit tests về determinism và null handling.

### Hoàn thành khi

- Có một entity key đủ giao dịch lặp để tính rolling feature.
- Giả định và hạn chế của key được ghi rõ.

---

## Phase 4 — Thiết kế Feature Registry

### Feature definition schema

Mỗi feature nên có:

```yaml
name: entity_transaction_amount_sum_24h
version: 1
entity_key: card_entity_id
source: silver_transactions
event_timestamp: event_time
value_expression: TransactionAmt
aggregation: sum
window: 24h
exclude_current_event: true
owner: data-engineering
description: Tổng giá trị giao dịch trước giao dịch hiện tại trong 24 giờ
```

### Feature set MVP

#### Velocity features

- [ ] `txn_count_1h`.
- [ ] `txn_count_6h`.
- [ ] `txn_count_24h`.
- [ ] `txn_count_7d`.

#### Amount features

- [ ] `amount_sum_1h`, `amount_sum_24h`, `amount_sum_7d`.
- [ ] `amount_avg_24h`, `amount_max_7d`.
- [ ] `current_amount_vs_avg_7d`.

#### Recency features

- [ ] `seconds_since_previous_txn`.
- [ ] `seconds_since_first_seen`.

#### Diversity features

- [ ] Số `ProductCD` khác nhau trong 7 ngày.
- [ ] Số email domain hoặc device khác nhau trong 7/30 ngày nếu dữ liệu đủ.

#### Identity/device features

- [ ] `has_identity`.
- [ ] `device_seen_before`.
- [ ] Số entity dùng cùng device trong quá khứ, nếu secondary entity đủ tin cậy.

### Quyết định quan trọng: có tính current event không?

Với fraud scoring tại thời điểm giao dịch, các thuộc tính của chính giao dịch hiện tại như amount và product có thể đã biết. Tuy nhiên, rolling history thường nên loại current event để tránh double counting:

```text
history_time < prediction_time
```

Nếu có nhiều giao dịch cùng timestamp, phải định nghĩa tie-breaker bằng `TransactionID`, hoặc chấp nhận rằng chúng cùng một event-time batch và không nhìn thấy nhau. Quy tắc này phải được ghi trong feature definition.

### Đầu ra

- Feature definitions trong YAML/JSON.
- `docs/feature_catalog.md`.
- Parser/validator cho feature definition.

### Hoàn thành khi

- Mỗi feature có entity, source, timestamp, window, aggregation, version và owner.
- Definition sai hoặc thiếu trường bị từ chối tự động.

---

## Phase 5 — Xây Point-in-Time Feature Computation

### Công việc

- [ ] Dùng mỗi transaction làm một observation/label row tại `prediction_time = event_time`.
- [ ] Join lịch sử theo `entity_key`.
- [ ] Bảo đảm feature event không vượt cutoff.
- [ ] Áp dụng đúng rolling window.
- [ ] Giữ label row không có history bằng left PIT join.
- [ ] Quy định cách xử lý current event và timestamp ties.
- [ ] Tạo output có feature values, feature version và computation metadata.
- [ ] Tính feature theo partition để tránh memory explosion.

### Invariant bắt buộc

Với mọi record được dùng để tính feature:

```text
history.entity_key = observation.entity_key
history.event_time < hoặc <= observation.prediction_time
history.event_time >= observation.prediction_time - window
```

Dùng `<` hay `<=` tùy definition, nhưng phải nhất quán.

### Golden dataset nhỏ

- [ ] Tạo một sample thủ công gồm vài entity và timestamp.
- [ ] Bao gồm no-match, cùng timestamp, null, late event và boundary của window.
- [ ] Tính expected feature values bằng tay.
- [ ] Dùng sample này làm regression test.

### Đầu ra

- PIT computation engine hoặc SQL jobs.
- Golden test dataset.
- Offline feature table partitioned theo thời gian.

### Hoàn thành khi

- Golden tests pass 100%.
- Không có record vi phạm cutoff.
- Số observation output bằng số label input.

---

## Phase 6 — Point-in-Time Correct Training Dataset Builder

### Temporal split đề xuất

Sắp xếp theo `TransactionDT`, sau đó chia theo thời gian, ví dụ:

- 60% đầu: train.
- 20% tiếp theo: validation.
- 20% cuối: internal test.

Hoặc dùng các mốc khác sau khi kiểm tra phân bố fraud, nhưng tuyệt đối không random split làm đánh giá chính.

### Công việc

- [ ] Tạo split boundaries bằng timestamp/quantile thời gian.
- [ ] Fit encoder/imputer chỉ trên training period.
- [ ] Materialize training dataset bằng PIT features.
- [ ] Lưu manifest: source snapshot, feature versions, cutoff range, row count và checksum.
- [ ] Kiểm tra không có temporal overlap giữa splits.
- [ ] Không dùng label tương lai để tạo aggregate feature.

### Leakage cần kiểm tra

- Future transactions lọt vào rolling window.
- Global mean/frequency encoding được fit trên toàn dataset.
- Imputation statistics được tính bằng validation/test.
- Random train/test split.
- Entity aggregation có sử dụng label `isFraud` trong tương lai.
- Feature đã được engineered trong dataset nhưng không rõ cách tính và có nguy cơ chứa tương lai.

Với các cột ẩn nghĩa `C/D/V`, nên tạo hai baseline:

1. **PIT feature baseline:** chỉ dùng feature nguồn rõ ràng và feature tự tạo.
2. **Extended baseline:** thêm các cột Kaggle sẵn có, đồng thời ghi rõ không thể kiểm chứng hoàn toàn logic tạo chúng.

### Đầu ra

- Versioned training/validation/test datasets.
- Dataset manifest.
- Leakage audit report.

### Hoàn thành khi

- Có thể tái tạo dataset từ manifest.
- Automated tests xác nhận không có temporal overlap và PIT violation.

---

## Phase 7 — Offline Feature Store và backfill

### Công việc

- [ ] Lưu feature theo entity, observation time và feature version.
- [ ] Chọn partition theo `event_date` hoặc month sau benchmark.
- [ ] Hỗ trợ đọc feature theo time range.
- [ ] Hỗ trợ backfill `start_time`–`end_time`.
- [ ] Backfill phải idempotent.
- [ ] Có strategy overwrite partition hoặc merge theo key.
- [ ] Ghi audit log cho mỗi materialization job.
- [ ] Gắn source snapshot và code/feature version.

### Materialization metadata

- Run ID.
- Feature set/version.
- Source checksum/version.
- Time range.
- Started/finished time.
- Row count.
- Output location.
- Job status.
- Quality-check results.

### Đầu ra

- Offline feature tables.
- Backfill command/API.
- Audit/materialization log.

### Hoàn thành khi

- Chạy lại cùng backfill không sinh duplicate.
- Cùng input version tạo cùng output checksum hoặc giá trị tương đương.

---

## Phase 8 — Baseline model để kiểm chứng usability

Model chỉ đóng vai trò consumer của Feature Store.

### Công việc

- [ ] Logistic Regression làm sanity baseline.
- [ ] LightGBM hoặc CatBoost làm tree baseline.
- [ ] Train trên chronological train split.
- [ ] Chọn hyperparameter trên validation period.
- [ ] Báo cáo một lần trên internal test period.
- [ ] So sánh raw baseline với PIT feature baseline.
- [ ] Log feature versions và dataset manifest cùng model.

### Metrics

- ROC-AUC.
- PR-AUC.
- Recall@FPR.
- Precision@K.
- Confusion matrix tại threshold đã chọn.

### Đầu ra

- Model artifact.
- Evaluation report.
- Feature importance hoặc explanation đơn giản.

### Hoàn thành khi

- Pipeline chứng minh training dataset dùng được.
- Kết quả có thể tái lập từ cùng manifest và seed.
- Không tuyên bố Feature Store tốt chỉ vì AUC cao; correctness tests vẫn là tiêu chí chính.

---

## Phase 9 — Online store và serving consistency

### Công việc

- [ ] Materialize feature mới nhất theo entity vào Redis.
- [ ] Key format có feature set và version.
- [ ] Lưu `feature_event_time` và `materialized_at`.
- [ ] Tạo API lookup theo entity.
- [ ] Trả về missing/default rõ ràng.
- [ ] Đo lookup latency.
- [ ] Replay một đoạn transaction stream theo `TransactionDT`.
- [ ] So sánh feature online với feature offline tại cùng cutoff.

### Ví dụ key

```text
feature:{feature_set_version}:{entity_id}
```

### Consistency checks

- Cùng logic aggregation.
- Cùng quy tắc `<` hoặc `<=` cutoff.
- Cùng null/default handling.
- Cùng kiểu dữ liệu và rounding.
- Sai khác nằm trong tolerance định trước.

### Đầu ra

- Online materialization job.
- Feature lookup API.
- Consistency report.

### Hoàn thành khi

- Sample entities đạt tỷ lệ consistency mục tiêu, lý tưởng 100% với feature deterministic.
- API trả cả feature value, version và timestamp.

---

## Phase 10 — Data quality, observability và orchestration

### Data quality checks

- Schema và type.
- Null rate.
- Uniqueness của `TransactionID`.
- Accepted values của `isFraud`.
- Non-negative amount/time.
- Identity join cardinality.
- Feature freshness.
- Feature value range.
- Drift theo time partition.

### Pipeline observability

- Runtime từng stage.
- Input/output row count.
- Bytes/partitions scanned.
- Số partition được prune.
- Retry/failure count.
- Feature freshness lag.
- Offline-online mismatch count.

### Orchestration DAG

```text
ingest
  └─> validate_raw
       └─> build_silver
            └─> validate_silver
                 └─> materialize_offline_features
                      ├─> build_training_dataset ─> train/evaluate
                      └─> materialize_online ─────> consistency_test
```

### Đầu ra

- Orchestrated workflow.
- Quality report.
- Pipeline metrics dashboard hoặc report.
- Runbook xử lý lỗi.

### Hoàn thành khi

- Một lệnh hoặc một workflow có thể chạy toàn pipeline.
- Job lỗi dừng đúng chỗ và tạo thông báo có thể điều tra.

---

## Phase 11 — Tối ưu theo paper FeathrPO

Chỉ bắt đầu phase này sau khi correctness tests đã ổn định.

### 11.1. Benchmark plan gốc

- [ ] Đo runtime.
- [ ] Đo bytes/files/partitions scanned.
- [ ] Đo peak memory nếu có thể.
- [ ] Ghi dataset size và cluster/machine configuration.

### 11.2. Time partitioning

- [ ] So sánh no partition, month, day và hour nếu khả thi.
- [ ] Đo partition pruning và overhead small files.
- [ ] Chọn granularity dựa trên workload, không chọn theo cảm tính.

### 11.3. Semi-join reduction

- [ ] Lấy `min(prediction_time)` và `max(prediction_time)` của label batch.
- [ ] Dùng khoảng này cộng window lớn nhất để pre-filter feature source.
- [ ] So sánh output checksum với plan gốc.
- [ ] Đo lượng scan giảm được.

### 11.4. Computation reuse

- [ ] Materialize `amount_sum_30d`.
- [ ] Tạo `amount_sum_60d` bằng kết quả 30 ngày cộng delta `[T-60d, T-30d)`.
- [ ] Xử lý null và no-history đúng.
- [ ] Kiểm tra semantic equivalence với full recomputation.
- [ ] Đo speedup.

### 11.5. Simple cost-based selection

- [ ] Ước lượng chi phí bằng bytes hoặc partitions cần scan.
- [ ] So sánh original plan và reuse plan.
- [ ] Chỉ chọn reuse khi chi phí dự kiến thấp hơn.
- [ ] Lưu decision vào execution metadata.

### Phần nâng cao tùy thời gian

- KLL sketch cho selectivity estimation.
- BIP chọn layout dưới rewrite budget.
- Tự động sinh candidate layout từ feature definitions.

### Đầu ra

- Benchmark report trước/sau.
- Semantic-equivalence tests.
- Execution-plan decision log.

### Hoàn thành khi

- Tối ưu cho kết quả feature giống plan chuẩn.
- Báo cáo được runtime và scan reduction trên cùng môi trường.

---

## Phase 12 — Documentation, demo và bàn giao

### Tài liệu bắt buộc

- [ ] README và quick start.
- [ ] Architecture diagram.
- [ ] Data contract.
- [ ] Entity-key decision record.
- [ ] Feature catalog.
- [ ] PIT correctness explanation.
- [ ] Leakage audit.
- [ ] Benchmark report.
- [ ] Operations runbook.
- [ ] Limitations và future work.

### Demo flow đề xuất

1. Hiển thị một giao dịch cần dự đoán tại cutoff `T`.
2. Hiển thị các event lịch sử được phép dùng.
3. Chèn một future event và chứng minh pipeline loại nó.
4. Materialize feature offline.
5. Tạo training dataset theo chronological split.
6. Train baseline model.
7. Replay event và truy vấn online feature.
8. So sánh offline-online values.
9. Chạy benchmark plan gốc và plan tối ưu.

### Hoàn thành khi

- Người khác clone project, cung cấp dataset đúng vị trí và chạy được theo hướng dẫn.
- Demo chứng minh cả correctness, reproducibility và performance.

---

## 8. Bộ kiểm thử tối thiểu

| Nhóm test | Trường hợp cần có |
|---|---|
| Schema | Thiếu cột, sai kiểu, cột thừa, schema drift. |
| Primary key | Duplicate/null `TransactionID`. |
| Join | Identity missing; nhiều identity row cho một transaction. |
| Entity | Null components; deterministic hash; singleton entity. |
| PIT cutoff | Event trước, đúng và sau cutoff. |
| Window | Event đúng boundary đầu/cuối window. |
| Same timestamp | Nhiều giao dịch cùng timestamp với tie-break rule. |
| No history | Label row vẫn xuất hiện với null/default feature. |
| Backfill | Chạy lại không duplicate và không đổi kết quả. |
| Partition | Pruning không làm mất record hợp lệ. |
| Reuse | Reuse/delta cho kết quả bằng full recomputation. |
| Consistency | Offline value bằng online value tại cùng cutoff. |
| Temporal split | Không overlap giữa train/validation/test. |

---

## 9. Tiêu chí thành công tổng thể

### Bắt buộc

- [ ] Không có PIT violation trong test suite.
- [ ] Training dataset được chia theo thời gian.
- [ ] Pipeline tái lập được từ config và source manifest.
- [ ] Feature definitions có version và lineage.
- [ ] Backfill idempotent.
- [ ] Có baseline model sử dụng PIT features.
- [ ] Có báo cáo giới hạn của surrogate entity và dataset.

### Tốt

- [ ] Có online store và consistency test.
- [ ] Có orchestration và data-quality checks.
- [ ] Có partition-pruning benchmark.
- [ ] Có feature reuse benchmark.

### Xuất sắc

- [ ] Có cost-based plan selection.
- [ ] Có streaming replay.
- [ ] Có drift/freshness monitoring.
- [ ] Có automated layout experiment hoặc KLL/BIP prototype.

---

## 10. Rủi ro và cách xử lý

| Rủi ro | Ảnh hưởng | Cách xử lý |
|---|---|---|
| Không có customer ID thật | Rolling features có thể gom sai entity | Dùng surrogate key, benchmark nhiều candidate và công khai giả định. |
| Feature ẩn nghĩa | Khó xác minh leakage của feature gốc | Tách PIT-only feature set khỏi extended Kaggle feature set. |
| Dataset lớn với laptop | Job chậm hoặc hết RAM | Parquet, column pruning, partitioning, DuckDB/Polars hoặc Spark; phát triển bằng sample. |
| Class imbalance | Accuracy gây hiểu nhầm | Dùng PR-AUC, ROC-AUC và operational metrics. |
| Random split | Kết quả quá lạc quan | Chỉ dùng chronological split làm đánh giá chính. |
| Same-timestamp events | Không rõ event nào được biết trước | Định nghĩa tie-breaker hoặc batch semantics rõ ràng. |
| Late-arriving data không có sẵn | Khó demo bitemporal behavior | Mô phỏng `ingestion_time` có kiểm soát và ghi rõ là synthetic. |
| Reuse làm sai kết quả | Tối ưu phá correctness | Semantic-equivalence test trước khi đo tốc độ. |
| Quá tập trung model | Lệch mục tiêu Data Engineering | Giới hạn model ở baseline; ưu tiên correctness và platform. |

---

## 11. Lộ trình thực hiện trong 5 tuần

Flow 5 tuần của chương trình là hợp lý và được dùng làm **lịch chính** của project:

```text
Chốt đề tài và dữ liệu
        ↓
Baseline chạy end-to-end
        ↓
MVP có thể demo
        ↓
Nhận feedback, tối ưu và xử lý edge case
        ↓
Đóng gói repo, báo cáo, slide và dry-run
```

Nguyên tắc triển khai xuyên suốt: **correctness trước, khả năng tái lập sau, tối ưu cuối cùng**. Sản phẩm cam kết là batch Point-in-Time Feature Store có offline store, PIT/leakage tests, training dataset và baseline model. Online serving là phần mở rộng nếu còn thời gian.

### Tuần 1 — Chọn đề tài, chọn dữ liệu và khảo sát sơ bộ

#### Mục tiêu

Chốt rõ bài toán, phạm vi, dataset và kết quả cuối kỳ; đồng thời xác minh IEEE-CIS có đủ điều kiện để triển khai Point-in-Time Feature Store.

#### Công việc

- [ ] Chốt problem statement: xây Point-in-Time Correct Feature Store phục vụ fraud detection.
- [ ] Xác định mục tiêu chính là Data Engineering/Feature Platform, không phải tối ưu leaderboard Kaggle.
- [ ] Đọc paper và mô tả chính thức của IEEE-CIS.
- [ ] Tải và kiểm kê bốn file transaction/identity của train và test.
- [ ] Khảo sát schema, số dòng, missing values, identity coverage và phân bố `isFraud`.
- [ ] Kiểm tra thứ tự thời gian của `TransactionDT`.
- [ ] Xác định các hạn chế: timestamp tương đối, không có customer ID thật, nhiều cột ẩn nghĩa.
- [ ] Đề xuất cách tạo synthetic `event_time` và surrogate entity key.
- [ ] Vẽ kiến trúc sơ bộ và chốt tech stack.
- [ ] Chốt feature MVP, tiêu chí kiểm thử và phạm vi 5 tuần.

#### Sản phẩm đầu ra

- **Đề cương một trang**, gồm:
  - Bài toán và lý do chọn.
  - Nguồn và đặc điểm dữ liệu.
  - Kiến trúc dự kiến.
  - Input/output của platform.
  - Các feature dự kiến.
  - Kết quả và demo mong đợi.
- Dataset inventory/profile sơ bộ.
- Project skeleton, environment và `.gitignore`.
- Danh sách rủi ro, giả định và tiêu chí thành công.

#### Điều kiện hoàn thành

- Mentor xác nhận đề tài và phạm vi.
- Dataset đọc được và `TransactionID` join được giữa transaction/identity.
- Đã biết rõ project sẽ demo điều gì vào tuần 3 và bàn giao gì vào tuần 5.

---

### Tuần 2 — Xây pipeline cơ bản chạy end-to-end

#### Mục tiêu

Có một **vertical slice tối thiểu** chạy từ dữ liệu nguồn đến PIT features và baseline model. Chưa cần đầy đủ tính năng hoặc tối ưu.

#### Công việc

- [ ] Xây ingestion CSV → Bronze → Silver.
- [ ] Cast schema, deduplicate và left join identity.
- [ ] Tạo synthetic `event_time` từ `TransactionDT`.
- [ ] Chọn một surrogate entity key đơn giản và deterministic.
- [ ] Tạo 3–5 feature đầu tiên, ví dụ `txn_count_24h`, `amount_sum_24h`, `amount_avg_7d`, `seconds_since_previous_txn`.
- [ ] Xây PIT computation bản đầu trên sample dữ liệu.
- [ ] Tạo chronological train/validation split đơn giản.
- [ ] Train một baseline model nhẹ.
- [ ] Viết smoke test và một leakage test cơ bản.
- [ ] Đóng gói thành một command/script chạy end-to-end.

#### Sản phẩm đầu ra

- Code chạy được:

```text
Raw CSV
  → Silver transactions
  → PIT features
  → Training dataset
  → Baseline model
  → Evaluation metrics
```

- Golden dataset nhỏ với expected output.
- README bản đầu có hướng dẫn setup và chạy baseline.
- Log kết quả lần chạy đầu tiên.

#### Điều kiện hoàn thành

- Một người khác có thể chạy pipeline trên sample bằng một chuỗi lệnh ngắn.
- Future event không xuất hiện trong ít nhất một PIT correctness test.
- Có metric baseline đầu tiên; metric chưa cần cao.

---

### Tuần 3 — Hoàn thiện MVP và demo trên dữ liệu thật

#### Mục tiêu

Nâng vertical slice thành MVP đúng bản chất Feature Store và chạy được trên IEEE-CIS train data.

#### Công việc

- [ ] Phân tích và chốt surrogate entity key có số liệu hỗ trợ.
- [ ] Hoàn thiện Feature Registry bằng YAML/JSON có version.
- [ ] Mở rộng lên 8–12 feature velocity, amount, recency và diversity.
- [ ] Hoàn thiện batch PIT Join và quy tắc current event/same timestamp.
- [ ] Materialize feature vào offline store Parquet/Delta.
- [ ] Thêm metadata: run ID, feature version, source checksum, time range và row count.
- [ ] Hoàn thiện chronological train/validation/internal-test split.
- [ ] Chạy pipeline trên dữ liệu thật hoặc một partition đủ lớn đại diện.
- [ ] Viết các test: cutoff, boundary window, no history, entity isolation và same timestamp.
- [ ] Tạo backfill cơ bản cho một time range nếu tiến độ cho phép.
- [ ] Chuẩn bị demo trực quan cho một transaction tại cutoff `T`.

#### Sản phẩm đầu ra

- **MVP demo được**, gồm:
  - Ingestion và Silver layer.
  - Surrogate entity.
  - Versioned feature definitions.
  - Point-in-Time feature computation.
  - Offline feature table.
  - Training dataset theo thời gian.
  - Baseline fraud model.
- Automated PIT correctness tests.
- Demo cho thấy event sau cutoff bị loại.

#### Điều kiện hoàn thành

- Golden tests pass 100%.
- Số observation output bằng số observation input.
- Không có PIT violation theo quy tắc đã định nghĩa.
- MVP chạy được trước buổi review giữa kỳ.

---

### Tuần 4 — Cải thiện theo feedback, tối ưu và xử lý edge case

#### Mục tiêu

Biến MVP thành phiên bản ổn định, có bằng chứng về correctness, chất lượng và hiệu năng.

#### Công việc ưu tiên theo feedback

- [ ] Sửa các vấn đề được mentor phát hiện trong demo tuần 3.
- [ ] Hoàn thiện leakage audit: temporal overlap, global encoding, imputation và future aggregation.
- [ ] Hoàn thiện backfill idempotent và kiểm tra chạy lại không duplicate.
- [ ] Bổ sung data-quality checks và audit/materialization log.
- [ ] Xử lý null entity, no-history, window boundary, timestamp ties và skewed entities.
- [ ] Benchmark PIT plan gốc: runtime, files/partitions/bytes scanned.
- [ ] Áp dụng time partitioning và partition pruning.
- [ ] Áp dụng semi-join reduction bằng min/max prediction time.
- [ ] So sánh checksum để chứng minh tối ưu không thay đổi feature values.
- [ ] Đánh giá model bằng ROC-AUC, PR-AUC, Recall@FPR và Precision@K.
- [ ] So sánh raw baseline với PIT-feature baseline.

#### Tính năng mở rộng nếu còn thời gian

- [ ] Redis online store.
- [ ] FastAPI feature lookup.
- [ ] Offline-online consistency test.
- [ ] Reuse feature 30 ngày để tính cửa sổ 60 ngày bằng delta.

#### Sản phẩm đầu ra

- Phiên bản ổn định sau feedback.
- Leakage/data-quality report.
- Performance benchmark trước và sau tối ưu.
- Model evaluation report.
- Danh sách edge cases đã kiểm thử và kết quả.

#### Điều kiện hoàn thành

- Tối ưu không làm thay đổi output logic.
- Có số liệu correctness và performance thay vì chỉ mô tả định tính.
- Các lỗi quan trọng đều có regression test.

---

### Tuần 5 — Hoàn thiện tài liệu, báo cáo, slide và dry-run

#### Mục tiêu

Đóng gói project thành sản phẩm có thể bàn giao, tái lập và trình bày rõ ràng.

#### Công việc

- [ ] Dọn repository, xóa notebook/script thử nghiệm không cần thiết.
- [ ] Bảo đảm không commit dataset, credential, cache hoặc model artifact quá lớn.
- [ ] Hoàn thiện README: kiến trúc, setup, commands, tests và demo flow.
- [ ] Hoàn thiện data contract, entity decision, feature catalog và runbook.
- [ ] Chốt bảng kết quả correctness, model metrics và performance benchmark.
- [ ] Viết báo cáo cuối kỳ: vấn đề, phương pháp, kiến trúc, thực nghiệm, giới hạn và future work.
- [ ] Làm slide trình bày.
- [ ] Chuẩn bị demo script và dữ liệu demo cố định.
- [ ] Dry-run toàn bộ báo cáo và demo; đo thời gian trình bày.
- [ ] Kiểm thử từ môi trường sạch hoặc máy/container mới.
- [ ] Tạo release/tag hoặc bản đóng gói cuối cùng.

#### Sản phẩm đầu ra

- **Báo cáo cuối kỳ**.
- **Repo gọn gàng, có hướng dẫn chạy**.
- **Slide trình bày**.
- **Bản demo ổn định**.
- Benchmark và test reports.
- Danh sách hạn chế và hướng phát triển tiếp theo.

#### Điều kiện hoàn thành

- Một người khác có thể setup và chạy sample pipeline theo README.
- Demo không phụ thuộc thao tác ngẫu hứng hoặc dữ liệu chưa chuẩn bị.
- Báo cáo phân biệt rõ phần đã hoàn thành, phần thử nghiệm và phần future work.

### Bảng tóm tắt chính thức

| Tuần | Mục tiêu | Sản phẩm đầu ra |
|---|---|---|
| **1** | Chọn đề tài, dữ liệu và khảo sát sơ bộ | Đề cương 1 trang, dataset profile, kiến trúc và phạm vi đã chốt |
| **2** | Xây pipeline/mô hình cơ bản đầu tiên | Code end-to-end tối thiểu trên sample, golden test và baseline metric |
| **3** | Hoàn thiện MVP, kiểm thử với dữ liệu thật | MVP Feature Store và demo PIT correctness |
| **4** | Cải thiện theo feedback, tối ưu và xử lý edge case | Phiên bản ổn định, leakage/quality report, model và performance metrics |
| **5** | Viết tài liệu, báo cáo, slide và dry-run | Báo cáo cuối, repo gọn gàng, slide và bản demo ổn định |

### Quy tắc cắt giảm phạm vi

Nếu tiến độ chậm, cắt theo thứ tự:

1. KLL/BIP automatic layout selection.
2. Online Redis/FastAPI.
3. Computation reuse nâng cao.
4. Orchestration framework phức tạp.

Không cắt:

- Golden dataset và PIT correctness tests.
- Chronological split.
- Leakage audit.
- Offline feature materialization.
- README và demo có thể tái lập.

### Chi tiết kỹ thuật tham khảo theo hạng mục

Phần dưới phân rã sâu hơn các hạng mục kỹ thuật. Đây là checklist tham khảo, không thay thế lịch chính ở trên.

### Hạng mục A — Dataset audit và nền tảng dữ liệu

#### Mục tiêu

Hiểu dataset, dựng skeleton project và tạo được canonical transaction dataset.

#### Công việc

- [ ] Tạo cấu trúc repository, môi trường chạy và `.gitignore`.
- [ ] Tải IEEE-CIS bằng Kaggle CLI; lưu checksum và không commit dữ liệu lớn.
- [ ] Profile bốn file transaction/identity của train và test.
- [ ] Kiểm tra schema, uniqueness của `TransactionID`, missing values và identity coverage.
- [ ] Phân tích `TransactionDT` và phân bố `isFraud` theo thời gian.
- [ ] Xây Bronze layer giữ nguyên dữ liệu nguồn.
- [ ] Xây Silver layer: cast type, deduplicate, left join identity và tạo `has_identity`.
- [ ] Tạo `event_time` từ một synthetic epoch cố định và ghi rõ đây không phải thời gian thật.
- [ ] Viết data contract và các kiểm tra schema cơ bản.

#### Đầu ra cuối tuần

- Pipeline raw → Bronze → Silver chạy được.
- `dataset_inventory.md`, data profile và data contract.
- Canonical transaction table ở Parquet/Delta, partition thử nghiệm theo time.
- Báo cáo rõ các giới hạn của dataset.

#### Tiêu chí nghiệm thu

- Không mất transaction sau khi left join identity.
- `TransactionID` và `event_time` qua các quality checks.
- Chạy lại pipeline cho kết quả giống nhau.

---

### Hạng mục B — Entity key, Feature Registry và golden dataset

#### Mục tiêu

Chốt entity dùng cho rolling features và đặc tả feature trước khi viết PIT engine.

#### Công việc

- [ ] Đánh giá các candidate entity key từ card/address/email fields.
- [ ] Đo cardinality, singleton rate, transactions/entity, null rate và skew.
- [ ] Chọn primary surrogate entity key và ghi decision record.
- [ ] Viết module hash deterministic và unit tests.
- [ ] Chốt quy tắc current event: rolling history dùng `history_time < prediction_time`.
- [ ] Chốt cách xử lý nhiều giao dịch cùng timestamp.
- [ ] Thiết kế schema Feature Registry dạng YAML/JSON.
- [ ] Định nghĩa 8–12 feature MVP: count, sum, average, max, recency và diversity.
- [ ] Tạo golden dataset nhỏ có expected outputs tính bằng tay.
- [ ] Bao gồm các case: no history, boundary window, same timestamp, null entity và future event.

#### Đầu ra cuối tuần

- `entity_key_decision.md`.
- Feature definitions có version.
- Feature-definition validator.
- Golden dataset và expected PIT results.

#### Tiêu chí nghiệm thu

- Entity hash deterministic.
- Mỗi feature có entity, source, timestamp, window, aggregation và version.
- Quy tắc cutoff/timestamp không còn mơ hồ.

---

### Hạng mục C — Point-in-Time engine và Offline Feature Store

#### Mục tiêu

Xây được phần cốt lõi của đề tài: feature computation không nhìn thấy tương lai.

#### Công việc

- [ ] Xây batch PIT Join bằng PySpark hoặc DuckDB/Polars theo stack đã chọn.
- [ ] Dùng mỗi giao dịch làm observation tại `prediction_time = event_time`.
- [ ] Tạo rolling features theo surrogate entity.
- [ ] Dùng left PIT join để giữ observation không có history.
- [ ] Materialize output vào offline feature store.
- [ ] Partition output theo time range phù hợp.
- [ ] Ghi metadata: run ID, feature version, source checksum, time range và row count.
- [ ] Viết backfill command theo `start_time`–`end_time`.
- [ ] Bảo đảm backfill idempotent.
- [ ] Viết test cho cutoff, window boundary, entity isolation, no-match và timestamp ties.
- [ ] Chạy golden dataset test và full-data smoke test.

#### Đầu ra cuối tuần

- PIT computation engine.
- Versioned offline feature tables.
- Backfill command cơ bản.
- Bộ automated PIT correctness tests.

#### Tiêu chí nghiệm thu

- Golden tests pass 100%.
- Không có `feature_event_time >= prediction_time` nếu definition dùng strict `<`.
- Số output observation bằng số input observation.
- Backfill chạy lại không sinh duplicate.

---

### Hạng mục D — Training dataset, leakage audit và baseline model

#### Mục tiêu

Chứng minh Feature Store tạo ra dataset dùng được cho ML mà vẫn đúng theo thời gian.

#### Công việc

- [ ] Chia train/validation/internal test theo thứ tự `TransactionDT`, không random split.
- [ ] Fit preprocessing chỉ trên training period.
- [ ] Xây versioned training dataset từ offline PIT features.
- [ ] Lưu manifest gồm source version, feature versions, cutoff range và checksum.
- [ ] Audit future leakage, temporal overlap, global encoding và imputation leakage.
- [ ] Tạo PIT-only baseline chỉ dùng raw fields rõ nghĩa và feature tự xây.
- [ ] Train Logistic Regression làm sanity baseline.
- [ ] Train LightGBM hoặc CatBoost làm tree baseline.
- [ ] Đánh giá ROC-AUC, PR-AUC, Recall@FPR và Precision@K.
- [ ] So sánh raw baseline với PIT-feature baseline.
- [ ] Bổ sung integration tests cho pipeline từ Silver tới training dataset.

#### Đầu ra cuối tuần

- Versioned train/validation/test datasets.
- Leakage audit report.
- Baseline model và evaluation report.
- Reproducible dataset/model manifest.

#### Tiêu chí nghiệm thu

- Không temporal overlap giữa ba split.
- Training dataset tái tạo được từ manifest.
- Model chỉ đóng vai trò kiểm chứng usability; không làm lệch trọng tâm sang leaderboard.

---

### Hạng mục E — Tối ưu, hardening, tài liệu và demo

#### Mục tiêu

Đo được lợi ích Data Engineering, đóng gói project và chuẩn bị demo hoàn chỉnh.

#### Công việc bắt buộc

- [ ] Benchmark plan PIT gốc: runtime, bytes/files/partitions scanned.
- [ ] Áp dụng time partitioning và đo partition pruning.
- [ ] Áp dụng semi-join reduction theo min/max prediction time.
- [ ] Kiểm tra output checksum/semantic equivalence trước và sau tối ưu.
- [ ] Chạy end-to-end workflow bằng một command hoặc orchestrated flow tối giản.
- [ ] Hoàn thiện quality checks, failure handling và audit log.
- [ ] Hoàn thiện README, architecture, feature catalog, runbook và limitations.
- [ ] Chuẩn bị demo future event bị loại khỏi PIT features.
- [ ] Viết báo cáo kết quả correctness, reproducibility và performance.

#### Công việc tùy thời gian

- [ ] Reuse `amount_30d` để tính `amount_60d` bằng delta và benchmark.
- [ ] Online store Redis và lookup API.
- [ ] Offline-online consistency test.
- [ ] Replay transaction stream theo `TransactionDT`.

#### Không ưu tiên trong 5 tuần

- KLL sketch hoàn chỉnh.
- BIP automatic layout selector.
- Streaming production architecture.
- Ensemble model hoặc tối ưu Kaggle leaderboard.

#### Đầu ra cuối tuần

- Benchmark report trước/sau tối ưu.
- End-to-end reproducible pipeline.
- Tài liệu và demo hoàn chỉnh.
- Danh sách future work rõ ràng.

#### Tiêu chí nghiệm thu

- Tối ưu không làm thay đổi feature values.
- Có số liệu runtime và scan reduction trên cùng môi trường.
- Người khác có thể chạy project theo README sau khi đặt dataset đúng vị trí.

### Tổng hợp phạm vi kỹ thuật

| Hạng mục | Trọng tâm | Deliverable quan trọng nhất |
|---|---|---|
| A | Data foundation | Bronze/Silver, profile và data contract. |
| B | Feature design | Surrogate entity, registry và golden dataset. |
| C | PIT correctness | PIT engine, offline store, backfill và tests. |
| D | ML usability | Chronological dataset, leakage audit và baseline model. |
| E | Engineering value | Optimization benchmark, hardening, docs và demo. |

### Phân bổ ưu tiên

- **60% thời gian:** correctness, data model, PIT engine và tests.
- **20% thời gian:** reproducibility, backfill, metadata và quality.
- **15% thời gian:** benchmark và tối ưu.
- **5% thời gian:** model baseline và presentation polish.

Nếu tiến độ bị chậm, cắt theo thứ tự: online serving → computation reuse → orchestration framework. Không cắt golden tests, leakage audit hoặc chronological split.

---

## 12. Việc cần làm ngay tiếp theo

1. [ ] Tạo cấu trúc repository và `.gitignore`.
2. [ ] Chọn PySpark hay DuckDB/Polars dựa trên tài nguyên máy.
3. [ ] Tải dataset bằng Kaggle CLI và lưu ngoài Git.
4. [ ] Viết script `ingest` có checksum và schema validation.
5. [ ] Tạo dataset profile.
6. [ ] Phân tích candidate entity keys.
7. [ ] Chốt quy tắc current-event và same-timestamp.
8. [ ] Viết 8–12 feature definitions đầu tiên.
9. [ ] Tạo golden dataset nhỏ trước khi xử lý full dataset.
10. [ ] Xây PIT Join MVP và leakage tests.

---

## 13. Tài liệu tham khảo

- Kaggle, **IEEE-CIS Fraud Detection — Dataset Description**: <https://www.kaggle.com/competitions/ieee-fraud-detection/data>
- Liu et al., **Optimizing Data Pipelines for Machine Learning in Feature Stores**, PVLDB 2023: <https://www.vldb.org/pvldb/vol16/p4230-camacho-rodriguez.pdf>
- Tài liệu lý thuyết nội bộ: [`LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md`](./LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md)

