# KIẾN TRÚC PIPELINE POINT-IN-TIME FEATURE STORE TRÊN GOOGLE CLOUD

## 1. Mục đích tài liệu

Tài liệu này mô tả kiến trúc dự kiến khi đưa pipeline Point-in-Time Correct Feature Store từ
máy local lên Google Cloud. Mục tiêu là trả lời bốn câu hỏi:

1. Code được đóng gói và phát hành như thế nào?
2. Dữ liệu đi qua các bước nào?
3. Dịch vụ Google Cloud nào chịu trách nhiệm cho từng bước?
4. Phần nào đã hoàn thành và phần nào vẫn đang được xây dựng?

Pipeline mang tính **batch**: mỗi ngày được kích hoạt một lần, xử lý dữ liệu mới rồi dừng. Các
Cloud Run Jobs không chạy liên tục khi không có dữ liệu cần xử lý.

## 2. Sơ đồ kiến trúc tổng thể

```mermaid
flowchart LR
    subgraph CICD["1. Đóng gói và phát hành code"]
        Git["GitHub repository"]
        CB["Cloud Build<br/>Build và kiểm thử"]
        AR["Artifact Registry<br/>Docker image có version"]

        Git --> CB --> AR
    end

    subgraph Trigger["2. Kích hoạt và điều phối"]
        CS["Cloud Scheduler<br/>Kích hoạt hằng ngày"]
        WF["Google Workflows<br/>Điều phối và theo dõi trạng thái"]

        CS --> WF
    end

    subgraph Compute["3. Các bước xử lý"]
        Bronze["Cloud Run Job<br/>Bronze ingestion"]
        Silver["Cloud Run Job<br/>Silver transformation"]
        PIT["Cloud Run Job<br/>Tính PIT features"]
        Score["Cloud Run Job<br/>Dự báo fraud"]

        Bronze -->|Thành công| Silver
        Silver -->|Thành công| PIT
        PIT -->|Thành công| Score
    end

    subgraph Storage["4. Cloud Storage"]
        Raw["raw/<br/>Dữ liệu nguồn"]
        BronzeData["bronze/<br/>Dữ liệu và ingest metadata"]
        SilverData["silver/<br/>Dữ liệu đã chuẩn hóa"]
        Offline["offline/<br/>PIT feature tables"]
        Models["models/<br/>Model có version"]
        Results["reports và predictions/<br/>Kết quả dự báo"]
        Manifest["manifests và catalog/<br/>Version, trạng thái publish"]
    end

    subgraph Observe["5. Truy vấn và theo dõi"]
        Logs["Cloud Logging"]
        Monitor["Cloud Monitoring<br/>Metric và cảnh báo"]
        BQ["BigQuery<br/>Truy vấn và demo"]
    end

    AR -. "Cùng một image, command khác nhau" .-> Bronze
    AR -.-> Silver
    AR -.-> PIT
    AR -.-> Score

    WF --> Bronze

    Raw --> Bronze
    Bronze --> BronzeData
    BronzeData --> Silver
    Silver --> SilverData
    SilverData --> PIT
    PIT --> Offline
    Offline --> Score
    Models --> Score
    Score --> Results

    Bronze -.-> Manifest
    Silver -.-> Manifest
    PIT -.-> Manifest
    Score -.-> Manifest

    Bronze -. "log" .-> Logs
    Silver -. "log" .-> Logs
    PIT -. "log" .-> Logs
    Score -. "log" .-> Logs
    Logs --> Monitor

    Offline -. "Bảng phục vụ demo" .-> BQ
    Results -.-> BQ
```

## 3. Luồng chạy hằng ngày

Ví dụ ngày 6/11, hệ thống nhận được dữ liệu giao dịch của ngày 5/11:

```mermaid
sequenceDiagram
    participant S as Cloud Scheduler
    participant W as Google Workflows
    participant B as Bronze Job
    participant V as Silver Job
    participant F as PIT Feature Job
    participant M as Fraud Scoring Job
    participant G as Cloud Storage

    S->>W: Kích hoạt processing_date=2026-11-05

    W->>B: Chạy Bronze ingestion
    B->>G: Ghi Bronze data và ingest manifest
    B-->>W: SUCCESS

    W->>V: Chạy Silver transformation
    V->>G: Ghi Silver partitions
    V-->>W: SUCCESS

    W->>F: Tính historical PIT features
    F->>G: Ghi offline feature table
    F-->>W: SUCCESS

    W->>M: Chấm điểm giao dịch ngày 5/11
    M->>G: Ghi predictions và report
    M-->>W: SUCCESS

    W-->>S: Pipeline hoàn thành
```

Nếu một bước thất bại, bước sau không được chạy. Ví dụ Silver thất bại:

```text
Bronze:      SUCCESS
Silver:      FAILED
PIT Feature: KHÔNG CHẠY
Scoring:     KHÔNG CHẠY
```

Workflows lưu trạng thái để xác định chính xác pipeline dừng ở đâu và bước nào cần chạy lại.

## 4. Một Docker image, nhiều Cloud Run Jobs

Docker không có nghĩa là toàn bộ pipeline bị gom thành một bước. Một image chứa code và thư
viện chung; mỗi Cloud Run Job gọi một command khác nhau.

| Cloud Run Job | Command dự kiến | Trách nhiệm |
|---|---|---|
| `pit-ingest` | `ingest-bronze` | Đưa raw data vào Bronze và thêm ingest metadata |
| `pit-silver` | `build-silver` | Chuẩn hóa kiểu, join identity, tạo event time và entity IDs |
| `pit-features` | `materialize-offline-features` | Tính historical features đúng theo thời điểm |
| `pit-score` | scoring command | Dùng model có version để dự báo giao dịch mới |

Luồng triển khai image:

```mermaid
flowchart LR
    Source["Source code"] --> Build["Cloud Build"]
    Build --> Test["PIT demo và non-root check"]
    Test -->|Pass| Registry["Artifact Registry"]
    Registry --> Ingest["pit-ingest"]
    Registry --> Silver["pit-silver"]
    Registry --> Features["pit-features"]
    Registry --> Score["pit-score"]
```

## 5. Vai trò từng dịch vụ

| Dịch vụ | Vai trò | Có chạy liên tục không? |
|---|---|---|
| Cloud Scheduler | Kích hoạt workflow theo lịch | Không |
| Google Workflows | Điều phối thứ tự, retry và failure path | Chỉ khi có execution |
| Cloud Run Jobs | Chạy từng batch Bronze/Silver/PIT/Scoring | Chạy xong rồi dừng |
| Cloud Storage | Lưu dữ liệu, model, report và manifest | Là storage, không phải compute |
| Artifact Registry | Lưu Docker image có version | Là storage, không phải compute |
| Cloud Build | Build và kiểm tra image | Chỉ khi phát hành phiên bản mới |
| Cloud Logging | Thu log của build và jobs | Nhận log khi có hoạt động |
| Cloud Monitoring | Metric, dashboard và cảnh báo | Dịch vụ quản lý |
| BigQuery | Truy vấn kết quả phục vụ demo/báo cáo | Chỉ tính phí theo cách sử dụng |

## 6. Vì sao không dùng Cloud Function cho toàn bộ pipeline?

Cloud Function phù hợp với logic nhỏ và phản ứng theo sự kiện, ví dụ:

```text
File mới được upload
→ kiểm tra tên file
→ gọi Workflow
```

Bronze, Silver và PIT materialization là batch processing nặng: đọc file lớn, join, tính rolling
features, ghi nhiều Parquet partitions và có thể cần nhiều RAM/thời gian. Cloud Run Jobs phù hợp
hơn vì job chạy đến khi hoàn thành, có cấu hình CPU/RAM/timeout/retry rõ ràng và dùng trực tiếp
Docker image đã kiểm thử.

Cloud Function có thể được bổ sung sau này làm trigger theo sự kiện:

```mermaid
flowchart LR
    File["File mới trong GCS"] --> Eventarc["Eventarc"]
    Eventarc --> Fn["Cloud Run Function<br/>Validate event"]
    Fn --> WF["Google Workflows"]
```

Với MVP cập nhật theo ngày, `Cloud Scheduler → Workflows` đơn giản và dễ kiểm soát hơn.

## 7. Publish dữ liệu an toàn

Cloud Storage FUSE không phải filesystem POSIX đầy đủ. Pipeline không coi việc đổi tên cả thư
mục là thao tác publish nguyên tử. Mỗi lần chạy sẽ ghi vào prefix riêng:

```text
silver/runs/<run_id>/...
offline/runs/<run_id>/...
```

Sau khi kiểm tra row count, schema, checksum và PIT quality thành công, pipeline mới cập nhật
manifest/catalog pointer để consumer nhìn thấy phiên bản mới:

```mermaid
flowchart LR
    Run["Ghi run-scoped prefix"] --> Validate["Data-quality checks"]
    Validate -->|Fail| Failed["Manifest: FAILED"]
    Validate -->|Pass| Publish["Manifest: PUBLISHED"]
    Publish --> Catalog["Cập nhật catalog pointer"]
    Catalog --> Consumer["Training hoặc scoring đọc version mới"]
```

## 8. Trạng thái triển khai hiện tại

### Đã hoàn thành

- [x] Cloud project, billing budget và region.
- [x] Cloud configuration và structured logging.
- [x] Docker runtime/test image Linux amd64, non-root.
- [x] Cloud Build dùng custom builder service account.
- [x] Artifact Registry dùng immutable tags.
- [x] Private Cloud Storage bucket, versioning, soft delete và lifecycle.
- [x] Runtime service account có quyền bucket tối thiểu.
- [x] Cloud Run job chạy future-event invariance demo thành công.
- [x] Cloud Run non-root container mount, ghi và đọc Cloud Storage thành công.

### Chưa hoàn thành

- [ ] Terraform/import toàn bộ hạ tầng đã tạo thủ công.
- [ ] Phát hành image bằng Git commit SHA.
- [ ] Cấu hình source paths dành cho cloud.
- [ ] Chạy Bronze và Silver trên dữ liệu thật ở cloud.
- [ ] Chạy full PIT materialization và đo CPU/RAM/runtime/cost.
- [ ] Run-scoped prefix, manifest state và catalog pointer an toàn.
- [ ] Workflows điều phối pipeline.
- [ ] Cloud Scheduler kích hoạt hằng ngày.
- [ ] Scoring job, BigQuery serving và monitoring dashboard.
- [ ] Backfill orchestration trên cloud.

## 9. Bằng chứng cloud hiện có

| Thành phần | Bằng chứng |
|---|---|
| Cloud Build | `583532b6-d303-403b-ae86-f5018a0bb027`, trạng thái `SUCCESS`, `2m34s` |
| Published image | Digest `sha256:007eb0a769c083efa48b45a6ffad4e2649c8be1b58959530d65e081895efd00d` |
| Cloud Run PIT demo | Execution `pit-features-5c8xt`, `1/1` task hoàn thành |
| Storage mount smoke test | Execution `pit-storage-smoke-w2fps`, ghi/đọc object thành công |

Job và object tạm của storage smoke test đã được xóa sau khi xác minh. Job `pit-features` vẫn
tồn tại nhưng không chạy liên tục; nó chỉ dùng compute khi được execute.
