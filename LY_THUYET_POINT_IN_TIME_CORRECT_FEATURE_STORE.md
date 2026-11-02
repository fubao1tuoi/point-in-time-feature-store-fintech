# Lý thuyết Point-in-Time Correct Feature Store

> Tóm tắt và diễn giải từ paper **“Optimizing Data Pipelines for Machine Learning in Feature Stores”** — Rui Liu và cộng sự, PVLDB 2023. Tài liệu được viết theo hướng dễ áp dụng vào đề tài **Point-in-Time Correct Feature Store cho Fintech**.

## 1. Paper giải quyết vấn đề gì?

Trong một hệ thống Machine Learning, dữ liệu thô phải đi qua nhiều bước trước khi trở thành feature dùng để huấn luyện hoặc dự đoán. Ví dụ, với bài toán phát hiện gian lận giao dịch, hệ thống có thể cần các feature như:

- Tổng số tiền khách hàng đã giao dịch trong 30 ngày gần nhất.
- Số giao dịch thất bại trong 24 giờ gần nhất.
- Số thiết bị khác nhau được sử dụng trong 7 ngày.
- Thời gian kể từ giao dịch gần nhất.

Các pipeline tạo feature thường phức tạp, tốn tài nguyên và dễ mắc lỗi về thời gian. Lỗi nguy hiểm nhất là **data leakage**: dữ liệu xảy ra sau thời điểm cần dự đoán lại vô tình được sử dụng làm feature trong lúc training.

Feature Store được tạo ra để quản lý tập trung việc định nghĩa, tính toán, lưu trữ và cung cấp feature. Tuy nhiên, paper nhận thấy các Feature Store hiện có tuy đáp ứng đúng chức năng nhưng vẫn tiêu tốn nhiều tài nguyên. Paper tập trung vào hai mục tiêu:

1. Bảo đảm việc tạo training dataset đúng theo thời gian bằng **Point-in-Time Join**.
2. Tối ưu pipeline Point-in-Time Join bằng cách **tái sử dụng kết quả đã tính** và **chọn cách phân vùng dữ liệu phù hợp**.

Nhóm tác giả hiện thực các kỹ thuật này trong **FeathrPO**, một phần mở rộng của Feature Store Feathr.

---

## 2. Feature Store là gì?

Feature Store có thể được hiểu là một hệ quản trị dữ liệu chuyên phục vụ Machine Learning. Nó thường đảm nhiệm ba chức năng chính:

1. Chạy pipeline chuyển dữ liệu thô thành feature.
2. Lưu trữ và quản lý feature.
3. Cung cấp feature cho training và inference.

### 2.1. Kiến trúc phổ biến

```text
Batch sources ─────┐
                   ├─> Compute Engine ─> Offline Store ─> Model Training
Streaming sources ─┘          │
                              └─────────> Online Store  ─> Online Inference

                 Feature Catalog quản lý definition, metadata và khả năng reuse
```

Các thành phần quan trọng:

| Thành phần | Vai trò |
|---|---|
| **Batch/streaming sources** | Nguồn giao dịch, ledger, customer profile, Kafka events hoặc dữ liệu trong warehouse/lakehouse. |
| **Compute engine** | Thực hiện join, filter, aggregation và transformation; paper sử dụng Spark. |
| **Offline store** | Tối ưu cho đọc dữ liệu lớn, chủ yếu phục vụ training và backfill. |
| **Online store** | Tối ưu cho truy vấn độ trễ thấp, phục vụ model inference theo từng entity. |
| **Feature catalog** | Lưu định nghĩa feature, nguồn dữ liệu, khóa, timestamp, lineage, materialization và metadata. |
| **SDK/API** | Cho phép Data Engineer định nghĩa pipeline và Data Scientist truy cập feature. |

Offline store và online store tồn tại riêng vì chúng có kiểu truy cập khác nhau:

- Training đọc lượng dữ liệu rất lớn nên ưu tiên throughput.
- Online inference thường đọc một vài feature của một entity nên ưu tiên latency thấp.

Ngoài các thành phần trên, Feature Store thực tế thường cần observability, monitoring và access control.

---

## 3. Point-in-Time Correctness

### 3.1. Khái niệm

Giả sử mô hình phải dự đoán gian lận cho giao dịch của khách hàng `A` tại thời điểm `T`. Training dataset chỉ được phép chứa những feature mà hệ thống **có thể biết tại hoặc trước `T`**.

Feature như “tổng tiền giao dịch 30 ngày gần nhất” phải được tính trên khoảng:

```text
T - 30 ngày <= transaction_time <= T
```

Không được đưa giao dịch sau `T` vào feature, vì khi dự đoán thật tại `T`, giao dịch tương lai đó chưa tồn tại.

### 3.2. Hai loại timestamp nên phân biệt khi triển khai

Paper tập trung vào timestamp dùng trong Point-in-Time Join. Khi triển khai thực tế, nên mô hình hóa rõ:

- **Event time:** thời điểm sự kiện thật sự xảy ra trong nghiệp vụ.
- **Ingestion/processing time:** thời điểm sự kiện được hệ thống nhận hoặc xử lý.

Point-in-time correctness thường dựa chủ yếu trên event time. Tuy nhiên, nếu cần mô phỏng đúng “thông tin mà hệ thống thật sự đã biết”, ingestion time cũng quan trọng, đặc biệt khi có dữ liệu đến muộn.

> Phân biệt hai timestamp là khuyến nghị triển khai cho đề tài; paper chủ yếu mô tả điều kiện PIT dựa trên timestamp của label và feature source.

### 3.3. Data leakage xảy ra như thế nào?

Ví dụ cần dự đoán giao dịch tại `2026-01-31 10:00`. Nếu pipeline tính tổng tiền theo toàn bộ ngày `2026-01-31`, một giao dịch lúc `15:00` có thể lọt vào feature của dự đoán lúc `10:00`.

Hậu quả:

- Kết quả đánh giá offline cao giả tạo.
- Khi chạy production, mô hình không có dữ liệu tương lai nên hiệu quả giảm mạnh.
- Training và serving không nhất quán.
- Việc phát hiện lỗi khó vì pipeline vẫn chạy thành công.

---

## 4. Point-in-Time Join

Point-in-Time Join, còn gọi là **PIT Join** hoặc **ASOF Join**, là phép join quan trọng nhất để tạo training dataset đúng theo thời gian.

### 4.1. Dữ liệu đầu vào

Một PIT Join thường có:

- **Label source:** mỗi dòng đại diện cho entity cần dự đoán tại một thời điểm cutoff `T`.
- **Feature source:** lịch sử sự kiện hoặc trạng thái có timestamp.
- **Entity key:** khóa liên kết, ví dụ `customer_id`, `account_id` hoặc `merchant_id`.
- **Window:** khoảng lịch sử được phép sử dụng.

Ví dụ:

```text
Label row:
customer_id = 101
prediction_time = 2026-01-31 10:00
is_fraud = 1

Feature source:
Các giao dịch của customer_id = 101 theo transaction_time
```

### 4.2. Điều kiện đúng

Với cửa sổ `W`, feature event hợp lệ khi:

```text
feature.entity_key = label.entity_key
AND label_time - W <= feature_time
AND feature_time <= label_time
```

Điều kiện `feature_time <= label_time` bảo đảm Point-in-Time Correctness. Điều kiện `feature_time >= label_time - W` giới hạn cửa sổ aggregation.

### 4.3. SQL minh họa

```sql
SELECT
    l.transaction_id,
    l.customer_id,
    l.label_time,
    l.is_fraud,
    SUM(f.amount) AS amount_30d
FROM fraud_labels AS l
LEFT JOIN transactions AS f
    ON f.customer_id = l.customer_id
   AND f.transaction_time >= l.label_time - INTERVAL '30' DAY
   AND f.transaction_time <= l.label_time
GROUP BY
    l.transaction_id,
    l.customer_id,
    l.label_time,
    l.is_fraud;
```

Paper tập trung vào **left PIT join** vì training dataset cần giữ lại cả label row không tìm thấy feature tương ứng. Việc không có lịch sử cũng có thể là một tín hiệu quan trọng, chẳng hạn khách hàng mới.

### 4.4. Trường hợp feature dạng trạng thái

Không phải feature nào cũng là aggregation. Với feature như “hạng loyalty gần nhất”, ta cần chọn bản ghi mới nhất nhưng không vượt quá cutoff:

```text
MAX(feature_time) sao cho feature_time <= label_time
```

Đây là ý nghĩa cốt lõi của ASOF/PIT join: lấy trạng thái đúng tại thời điểm lịch sử, không lấy trạng thái hiện tại rồi gán ngược về quá khứ.

---

## 5. Những cơ hội tối ưu được paper chỉ ra

Paper liệt kê năm cơ hội tối ưu trong Feature Store:

| Mã | Cơ hội | Vấn đề hiện tại |
|---|---|---|
| **O1** | Feature computation reuse | Nhiều feature hoặc lần thử nghiệm lặp lại phần tính toán cũ nhưng Data Engineer phải tự phát hiện. |
| **O2** | Data source layout | Dữ liệu không được bố trí phù hợp với filter theo thời gian, dẫn đến scan thừa. |
| **O3** | Incremental feature refresh | Dữ liệu chỉ thay đổi một phần nhỏ nhưng feature thường bị tính lại từ đầu. |
| **O4** | Feature maintenance scheduling | Lịch refresh đơn giản, chưa xét freshness, dependency và tài nguyên compute. |
| **O5** | Compute engine selection | Việc chọn engine thường cố định hoặc giao thủ công cho Data Engineer. |

Phạm vi thực nghiệm của paper chỉ giải quyết trực tiếp:

- **O1:** tái sử dụng feature/training dataset đã materialize.
- **O2:** tự động chọn layout dữ liệu cho pipeline PIT Join.

O3, O4 và O5 là hướng mở, không nên trình bày như kết quả đã được paper giải quyết.

---

## 6. Tối ưu 1 — Tái sử dụng feature đã tính

### 6.1. Ý tưởng

Quá trình phát triển ML có tính lặp. Data Scientist có thể thử feature tổng giao dịch trong 7, 14, 30 và 40 ngày. Nếu `amount_30d` đã được tính và materialize, việc tính `amount_40d` không nhất thiết phải đọc và tổng hợp lại toàn bộ 40 ngày.

Ta có thể tính:

```text
amount_40d = amount_30d + amount trong [T - 40 ngày, T - 30 ngày)
```

Phần chưa được tính trước đó được gọi là **delta**.

Nếu cửa sổ mới nhỏ hơn cửa sổ cũ, ví dụ từ 30 ngày xuống 10 ngày, việc rewrite phức tạp hơn và có thể áp dụng ý tưởng từ incremental view maintenance.

### 6.2. Quy trình tối ưu của FeathrPO

```text
Feature definition mới
        │
        ▼
     Matcher ── kiểm tra feature/materialization cũ có còn hợp lệ không
        │
        ▼
     Rewriter ─ tạo các execution plan tương đương có sử dụng kết quả cũ
        │
        ▼
 Cost Estimator ─ so sánh chi phí plan gốc và các plan rewrite
        │
        ▼
 Compute Engine ─ chạy plan tốt nhất
        │
        ▼
 Feature Catalog ─ đăng ký kết quả và metadata mới
```

#### Matcher

Matcher đọc Feature Catalog và xác định:

- Materialization cũ có dùng đúng nguồn dữ liệu không?
- Nguồn dữ liệu có thay đổi kể từ lần materialize gần nhất không?
- Kết quả mới có được chứa hoàn toàn hoặc một phần trong kết quả cũ không?

Nếu nguồn đã thay đổi mà kết quả cũ chưa được refresh, materialization có thể không còn hợp lệ để reuse.

#### Rewriter

Rewriter tạo pipeline mới có cùng ngữ nghĩa với pipeline gốc nhưng tận dụng kết quả đã materialize. Nó có thể xử lý:

- **Full containment:** kết quả cần thiết đã nằm hoàn toàn trong dữ liệu cũ.
- **Partial containment:** chỉ một phần có sẵn; phần còn lại phải tính thêm.

Điều kiện quan trọng là rewritten plan phải cho kết quả tương đương với plan gốc, bao gồm cả cách xử lý `NULL`.

#### Cost Estimator

Không phải reuse lúc nào cũng nhanh hơn. Cost Estimator so sánh các plan và chỉ chọn rewrite khi chi phí dự kiến thấp hơn.

### 6.3. Semi-join reduction

Paper còn giảm lượng dữ liệu phải scan bằng cách lấy `min(label_time)` và `max(label_time)` của training dataset, sau đó dùng khoảng này để lọc feature source trước PIT Join.

Ví dụ, nếu toàn bộ label chỉ nằm trong tháng 1, không cần scan feature partition của cả năm.

Kỹ thuật này đặc biệt hiệu quả khi kết hợp với partitioning theo thời gian, vì compute engine có thể bỏ qua hoàn toàn các partition không liên quan.

Semi-join reduction có thể dùng ngay cả khi không áp dụng feature reuse.

---

## 7. Tối ưu 2 — Data layout và partitioning

### 7.1. Vì sao layout ảnh hưởng lớn?

Trong PIT Join:

- Feature source thường lớn hơn label source rất nhiều.
- Join dùng entity key nhưng dữ liệu bị lọc mạnh theo time window.
- Feature source thường tăng dần theo thời gian.

Vì vậy, partition feature source theo thời gian cho phép hệ thống thực hiện **partition pruning**: chỉ đọc những partition có thể chứa dữ liệu thuộc cửa sổ PIT.

Các candidate layout mà paper xem xét gồm partition theo:

- Năm.
- Tháng.
- Ngày.
- Giờ.
- Hoặc không partition.

Partition quá thô làm scan thừa. Partition quá nhỏ tạo quá nhiều file/partition, làm tăng chi phí planning và scheduling. Do đó không có một granularity tối ưu cho mọi workload.

### 7.2. Cost model

Paper dùng lượng dữ liệu bị scan làm đại diện cho chi phí pipeline:

```text
Cost(pipeline) = tổng kích thước source − lợi ích do layout mang lại
```

Lợi ích của một layout được đánh giá theo thứ tự ưu tiên:

1. Kích thước các partition có thể bỏ qua hoàn toàn.
2. Lượng dữ liệu có thể filter sau khi đọc partition.
3. Số partition cần đọc, vì nhiều partition làm tăng overhead.

Để ước lượng selectivity của điều kiện thời gian mà không xây histogram tốn kém, paper sử dụng **KLL sketch** để ước lượng quantile.

Giả định trong paper là dữ liệu **append-only**. Dữ liệu có update/delete nằm ngoài phạm vi cost model được đánh giá.

### 7.3. Automatic Layout Selection

Quy trình lựa chọn layout:

1. Đọc feature definitions từ Feature Catalog.
2. Tìm các source có time dimension và được filter theo time.
3. Sinh candidate partitioning theo year/month/day/hour.
4. Ước lượng lợi ích và chi phí cho workload.
5. Chọn cấu hình tối ưu.
6. Controller thực hiện repartition và cập nhật catalog.

Paper dùng **Binary Integer Programming (BIP)** để chọn cấu hình. Các ràng buộc chính:

- Mỗi source chỉ chọn đúng một partitioning strategy.
- “Không partition” cũng là một lựa chọn.
- Tổng kích thước dữ liệu phải rewrite không vượt ngân sách `B`.

Ngân sách `B` giúp tránh việc tối ưu layout chiếm quá nhiều thời gian hoặc ảnh hưởng các job training/inference khác.

Layout selector được chạy định kỳ, phù hợp với workload tương đối ổn định. Việc tự chọn thời điểm tối ưu hoặc phản ứng theo workload thay đổi là hướng nghiên cứu tương lai.

---

## 8. Cách FeathrPO được triển khai

FeathrPO mở rộng Feathr với hai module chính:

1. **Reuse-based Optimizer** để match, rewrite và chọn plan tái sử dụng feature.
2. **Data Layout Selector** để chọn partitioning strategy.

Feathr sử dụng:

- Python client để định nghĩa feature và job.
- Spark để tính toán feature.
- Feature registry/catalog để lưu metadata.
- Connector cho offline và online stores.

Feature Catalog được mở rộng để lưu:

- Định nghĩa materialized feature.
- Đường dẫn lưu dữ liệu.
- Partitioning strategy hiện tại.
- Thay đổi layout.
- Thống kê của source dataset.

Điểm đáng chú ý là tối ưu được đặt ở lớp Feature Store thay vì sửa riêng compute engine. Nhờ vậy, ý tưởng có thể áp dụng với nhiều engine hoặc nhiều cách cài đặt PIT Join, miễn là Feature Store có đủ metadata và khả năng rewrite execution plan.

---

## 9. Kết quả thực nghiệm

Paper đánh giá trên:

- Hai use case của TPCx-AI, trong đó có fraud detection.
- Favorita.
- Một dataset e-commerce.

Kết quả chính:

- FeathrPO nhanh hơn Feathr baseline tối đa **3,0 lần**.
- Khi áp dụng cho các PIT Join implementation khác, mức tăng tốc đạt khoảng **1,4–2,5 lần**.
- FeathrPO có khả năng scale tốt hơn baseline khi kích thước dữ liệu tăng.
- Cost model dựa trên KLL tránh performance regression trong các thí nghiệm của paper.
- Bài toán BIP với 10.000 query và 1.000 source dataset được giải trong khoảng 6–7 giây trong thiết lập của tác giả.

Các con số trên chứng minh lợi ích trong thiết lập thực nghiệm của paper, không phải cam kết rằng mọi hệ thống production đều đạt đúng mức tăng tốc đó.

---

## 10. Áp dụng vào đề tài Point-in-Time Correct Feature Store cho Fintech

### 10.1. Mục tiêu đề tài nên ưu tiên

Một phiên bản khả thi nên ưu tiên correctness trước performance:

1. Tạo training dataset không bị future leakage.
2. Cho phép định nghĩa entity key, event timestamp và aggregation window.
3. Lưu feature definition và lineage trong catalog.
4. Hỗ trợ backfill có thể tái lập.
5. Đối chiếu feature dùng lúc training với feature tại serving.
6. Sau khi đúng mới triển khai partition pruning và computation reuse.

### 10.2. Use case fintech gợi ý

Use case phù hợp nhất là tạo feature cho fraud scoring:

| Nhóm | Ví dụ feature |
|---|---|
| Velocity | Số giao dịch trong 5 phút, 1 giờ và 24 giờ. |
| Amount | Tổng/ trung bình/ lớn nhất trong 1, 7 và 30 ngày. |
| Device | Số thiết bị hoặc IP khác nhau trong 7 ngày. |
| Merchant | Tỷ lệ giao dịch thất bại với merchant trong 24 giờ. |
| Customer history | Thời gian từ giao dịch gần nhất; số chargeback trước cutoff. |

Mỗi giao dịch cần dự đoán đóng vai trò một label row với `prediction_time`. Các feature lịch sử chỉ được lấy tại hoặc trước thời điểm này.

### 10.3. Data model tối thiểu

```text
transactions
├── transaction_id
├── customer_id
├── merchant_id
├── amount
├── status
├── event_time
└── ingestion_time

fraud_labels
├── transaction_id
├── customer_id
├── prediction_time
└── is_fraud

feature_definitions
├── feature_name
├── entity_key
├── source
├── event_timestamp_column
├── aggregation
├── window
├── version
└── owner
```

### 10.4. Pipeline đề xuất

```text
Raw transactions
      │
      ▼
Bronze: dữ liệu nguyên bản, append-only
      │
      ▼
Silver: chuẩn hóa schema, timestamp, deduplication
      │
      ├───────────────┐
      ▼               ▼
PIT feature job    Online materialization
      │               │
      ▼               ▼
Offline Store      Online Store
      │               │
      ▼               ▼
Training dataset   Fraud inference API
```

Offline feature computation nên partition theo ngày hoặc tháng của `event_time`, tùy data volume và window phổ biến.

### 10.5. Các kiểm thử bắt buộc

#### Test chống leakage

Với mỗi output row, xác nhận:

```text
max(feature_event_time) <= prediction_time
```

#### Test cửa sổ

Không feature event nào được nằm trước `prediction_time - window`.

#### Test entity isolation

Feature của khách hàng này không được join sang khách hàng khác.

#### Test no-match

Label không có lịch sử vẫn phải tồn tại trong training dataset nếu dùng left PIT join.

#### Test late-arriving data

Xác định rõ khi event đến muộn thì backfill cập nhật partition và feature nào.

#### Test reproducibility

Cùng source snapshot, feature definition và cutoff phải tạo ra cùng một training dataset.

#### Test training-serving consistency

Với cùng entity và cutoff, logic tính feature offline và online phải có cùng định nghĩa; cho phép sai số số học trong ngưỡng đã định.

### 10.6. Roadmap triển khai hợp lý

#### Giai đoạn 1 — Correctness MVP

- Batch source dạng Parquet/Delta.
- Một entity key và một số window aggregates.
- Left PIT Join bằng Spark SQL.
- Feature definition bằng YAML/JSON.
- Unit test chống leakage.

#### Giai đoạn 2 — Feature Store cơ bản

- Feature Catalog.
- Offline materialization.
- Backfill theo khoảng thời gian.
- Versioning và lineage.
- Data quality checks.

#### Giai đoạn 3 — Online serving

- Materialize feature mới nhất sang Redis hoặc store tương đương.
- API lookup theo entity.
- Kiểm tra training-serving consistency.
- Theo dõi freshness và latency.

#### Giai đoạn 4 — Tối ưu theo paper

- Partition pruning theo event time.
- Semi-join reduction bằng min/max cutoff.
- Nhận diện feature/window đã materialize.
- Reuse kết quả và chỉ tính delta.
- So sánh plan gốc với plan reuse bằng data scanned và runtime.

Automatic layout selection bằng KLL + BIP có thể là phần nâng cao. Không nhất thiết phải hoàn thiện ngay trong MVP nếu thời gian thực tập hạn chế.

---

## 11. Các chỉ số đánh giá đề tài

### Correctness

- Số vi phạm `feature_time > prediction_time`: phải bằng 0.
- Tỷ lệ training rows được tạo đúng.
- Tỷ lệ feature nhất quán giữa offline và online.
- Khả năng tái lập khi chạy lại cùng snapshot/version.

### Performance

- Runtime tạo training dataset.
- Tổng bytes/partitions được scan.
- Tỷ lệ partition pruning.
- Mức tăng tốc khi reuse feature cũ.
- Chi phí compute cho mỗi lần backfill.

### Reliability

- Feature freshness.
- Tỷ lệ job thành công.
- Số bản ghi duplicate hoặc thiếu key/timestamp.
- Thời gian khôi phục hoặc chạy lại job thất bại.

---

## 12. Những điều paper không giải quyết hoàn toàn

Khi sử dụng paper làm nền tảng, cần ghi rõ các giới hạn:

- Paper tập trung chủ yếu vào offline store và training pipeline, không tối ưu sâu online serving.
- Cost model giả định dữ liệu append-only; update/delete phức tạp hơn.
- Phần rewrite được mô tả cho left PIT join; các loại join khác là hướng mở.
- Incremental refresh, scheduling và automatic compute-engine selection được nêu là cơ hội nhưng chưa được giải quyết trong paper.
- Production cần xử lý thêm concurrent writes, schema evolution, access control, privacy và disaster recovery.
- Point-in-time correctness không tự động bảo đảm label đúng, dữ liệu sạch hoặc model không bias.

---

## 13. Kết luận dễ nhớ

Có thể tóm tắt tư tưởng của paper thành hai lớp:

### Lớp 1 — Correctness

> Với mỗi label tại thời điểm `T`, chỉ dùng feature mà hệ thống có thể biết tại hoặc trước `T`.

Điều này được thực hiện bằng entity key, cutoff timestamp, window và PIT Join.

### Lớp 2 — Efficiency

> Không tính lại và không đọc lại dữ liệu khi không cần thiết.

Paper thực hiện điều này bằng:

- Tái sử dụng feature/training dataset đã materialize.
- Chỉ tính phần delta.
- Semi-join reduction.
- Partitioning theo thời gian.
- Cost model để chọn execution plan.
- BIP để chọn layout cho toàn workload dưới giới hạn chi phí rewrite.

Đối với đề tài đã chọn, giá trị quan trọng nhất không phải chỉ là “xây một nơi lưu feature”, mà là xây một pipeline có thể chứng minh rằng:

1. Training data không nhìn thấy tương lai.
2. Feature có định nghĩa và lineage rõ ràng.
3. Backfill có thể tái lập.
4. Training và serving sử dụng logic nhất quán.
5. Hệ thống giảm được data scan và computation thừa.

---

## Nguồn

- Rui Liu et al., **Optimizing Data Pipelines for Machine Learning in Feature Stores**, Proceedings of the VLDB Endowment, Vol. 16, No. 13, 2023.
- Paper: <https://www.vldb.org/pvldb/vol16/p4230-camacho-rodriguez.pdf>
- DOI: <https://doi.org/10.14778/3625054.3625060>

