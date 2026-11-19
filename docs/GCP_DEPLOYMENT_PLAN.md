# Kế hoạch triển khai Point-in-Time Feature Store trên Google Cloud

## 1. Mục tiêu

Đưa pipeline local hiện tại lên Google Cloud theo hình thức batch platform có thể:

- chạy full pipeline bằng container;
- nhận một batch giao dịch mới theo ngày;
- tạo Bronze, Silver và PIT features có version;
- score các giao dịch mới bằng model đã được phê duyệt;
- backfill một khoảng ngày an toàn và idempotent;
- được kích hoạt tự động, theo dõi bằng log/metric và cảnh báo khi lỗi;
- tái tạo kết quả local trong sai số cho phép.

Phạm vi này chưa xây online feature API hoặc streaming real time. IEEE-CIS là dataset tĩnh nên
daily ingestion sẽ được mô phỏng bằng cách đưa từng partition ngày vào vùng raw.

## 2. Kiến trúc mục tiêu

```text
Daily file / simulated IEEE-CIS partition
                    │
                    ▼
            Cloud Storage — raw
                    │
        Cloud Scheduler theo lịch hằng ngày
                    │
                    ▼
              Google Workflows
                    │
     ┌──────────────┼──────────────────┐
     ▼              ▼                  ▼
Cloud Run Job   Cloud Run Job      Cloud Run Job
Bronze/Silver   PIT features       score + quality
     │              │                  │
     └──────────────┴──────────────────┘
                    ▼
        Cloud Storage versioned lake
 raw / bronze / silver / offline / models / reports
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       BigQuery        Cloud Logging/Monitoring
       query/demo      logs, metrics, alerts

GitHub → Cloud Build → Artifact Registry → Cloud Run Jobs
Terraform → bucket, IAM, jobs, workflow, scheduler, alerts
```

Tài liệu Google Cloud xác nhận Cloud Run Jobs chạy container batch, hỗ trợ cấu hình retry,
timeout và tài nguyên; Workflows có thể được Cloud Scheduler kích hoạt theo lịch. Tham khảo:

- [Cloud Run Jobs](https://docs.cloud.google.com/run/docs/create-jobs)
- [Schedule Workflows](https://docs.cloud.google.com/workflows/docs/schedule-workflow)
- [Artifact Registry](https://docs.cloud.google.com/artifact-registry/docs/overview)
- [Cloud Build và Docker image](https://docs.cloud.google.com/build/docs/build-push-docker-image)

## 3. Các quyết định kiến trúc

### 3.1. Compute: Cloud Run Jobs

Giữ code Python/DuckDB hiện tại và đóng gói thành Linux container. Mỗi job nhận command và
runtime parameters như `processing_date`, `run_id`, `feature_version` và `mode`.

Cloud Run Jobs phù hợp vì workload là batch, không cần server chạy liên tục. Job hiện hỗ trợ
timeout tối đa 7 ngày và memory tối đa 32 GiB. Lần chạy local của bước PIT đã dùng nhiều RAM,
nên spike đầu tiên sẽ thử offline job với `8 vCPU / 32 GiB`; các job nhẹ bắt đầu ở `2–4 vCPU /
4–8 GiB`, rồi điều chỉnh bằng metric thay vì giữ cấu hình quá lớn.

Tham khảo [memory limits cho Cloud Run Jobs](https://docs.cloud.google.com/run/docs/configuring/jobs/memory-limits).

### 3.2. Storage: Cloud Storage + Parquet

Cloud Storage là system of record cho raw, processed data, model và report. BigQuery dùng để
truy vấn và demo, không thay thế toàn bộ data lake trong MVP.

Đề xuất một private bucket theo môi trường:

```text
gs://<project>-pit-feature-store-dev/
  raw/ieee_cis/v1/ingestion_date=YYYY-MM-DD/
  bronze/v1/run_id=<run_id>/
  silver/v1/run_id=<run_id>/event_date=YYYY-MM-DD/
  offline/transaction_features/v1/run_id=<run_id>/observation_date=YYYY-MM-DD/
  training/v1/run_id=<run_id>/
  models/fraud_detection/v1/run_id=<run_id>/
  reports/run_id=<run_id>/
  manifests/run_id=<run_id>/
  catalog/
```

Bucket không public. Bật object versioning trong giai đoạn thử nghiệm và lifecycle rule để xóa
staging/temporary objects sau một khoảng thời gian đã thống nhất.

### 3.3. Không dùng local rename làm publish contract trên GCS

Cloud Run writable filesystem nằm trong memory và không tồn tại sau khi job dừng. Cloud Storage
volume mount dùng Cloud Storage FUSE, không cung cấp đầy đủ POSIX semantics hoặc concurrency
control cho nhiều writer. Vì vậy không phụ thuộc vào `rename directory` như local.

Publish contract trên cloud:

```text
1. Ghi output vào immutable run prefix.
2. Ghi manifest trạng thái staging.
3. Chạy row count, uniqueness, checksum/fingerprint và cutoff checks.
4. Nếu pass, ghi published manifest vào manifests/run_id=.../.
5. Cập nhật catalog pointer nhỏ, ví dụ catalog/offline_features_v1.json.
6. Consumer chỉ đọc run_id được catalog trỏ tới.
```

Nếu job fail, catalog không đổi nên consumer vẫn đọc version trước. Retry cùng `run_id` phải
kiểm tra object đã tồn tại và không tạo duplicate. Tài liệu liên quan:

- [Cloud Run filesystem contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Cloud Storage volume mounts](https://docs.cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts)
- [Cloud Run retry/checkpoint practices](https://docs.cloud.google.com/run/docs/jobs-retries)

### 3.4. Hai pipeline khác nhau

Không train model mỗi ngày.

```text
Daily operational pipeline
raw → Bronze → Silver → PIT features → score → publish report

Periodic/manual training pipeline
labeled Silver + offline PIT → training dataset → train → evaluate → approve model
```

Daily job dùng model version đã được phê duyệt trong model catalog. Training chỉ chạy khi có
label mới hoặc theo lịch riêng, ví dụ hằng tuần/tháng trong demo.

### 3.5. BigQuery

Giai đoạn đầu tạo external table hoặc load các bảng nhỏ cần demo từ Parquet trên Cloud Storage:

- daily scored transactions;
- daily data-quality summary;
- model evaluation summary;
- run status và lineage.

External table giúp truy vấn file mà chưa cần copy toàn bộ vào BigQuery. Bảng dùng thường xuyên
có thể load thành managed table. Cloud Storage bucket và BigQuery dataset phải dùng location
tương thích. Tham khảo [BigQuery external tables](https://docs.cloud.google.com/bigquery/docs/external-tables)
và [load Parquet từ Cloud Storage](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-parquet).

## 4. Các thành phần cần tạo

| Thành phần | Tên gợi ý | Vai trò |
|---|---|---|
| GCP project | `pit-feature-store-dev` | Cô lập tài nguyên thử nghiệm |
| Region | Một region chung, ưu tiên gần người dùng | Giảm phức tạp location/egress |
| Cloud Storage bucket | `<project>-pit-feature-store-dev` | Versioned data lake |
| Artifact Registry | `pit-feature-store` | Lưu Docker images |
| Cloud Build | `cloudbuild.yaml` | Test, build và push image |
| Service account | `pit-pipeline-runner` | Quyền tối thiểu cho runtime |
| Service account | `pit-workflow-invoker` | Workflows gọi Cloud Run Jobs |
| Service account | `pit-scheduler-invoker` | Scheduler gọi Workflows |
| Cloud Run Jobs | `pit-ingest`, `pit-features`, `pit-score` | Batch execution |
| Workflows | `pit-daily-pipeline` | Điều phối thứ tự và failure path |
| Cloud Scheduler | `pit-daily-trigger` | Kích hoạt hằng ngày |
| BigQuery dataset | `pit_feature_store_ops` | Query và demo |
| Monitoring | dashboard + alerts | Theo dõi duration, failure, memory |
| Secret Manager | Chỉ khi có secret thật | Không ghi credential trong image/Git |

## 5. Kế hoạch thực hiện theo tuần

### Tuần 3 — Container hóa và chạy thủ công trên cloud

#### 3.1. Chuẩn hóa cloud configuration

- [x] Chốt `project_id`, billing account, region và naming convention.
- [x] Tạo `configs/cloud/dev.yaml` không chứa secret.
- [x] Tách path local khỏi code; mọi source/output root nhận qua CLI hoặc environment variable.
- [x] Chuẩn hóa structured log: `run_id`, `stage`, `processing_date`, `version`, `row_count`,
  `status`, `duration_seconds`.

**Hoàn thành khi:** cùng container có thể chạy với local path và `/mnt/data` path mà không sửa
source code.

#### 3.2. Docker

- [x] Viết multi-stage `Dockerfile` Linux amd64.
- [x] Thêm `.dockerignore`; không copy raw data, output, `.venv`, paper hoặc credential.
- [x] Container chạy bằng non-root user.
- [x] Thêm entrypoint gọi từng pipeline command.
- [x] Chạy unit/integration tests trong Docker local.

**Hoàn thành khi:** image build thành công và demo future-event invariance pass trong container.

#### 3.3. Infrastructure foundation

- [ ] Tạo `infra/terraform/` cho APIs, bucket, Artifact Registry, service accounts và IAM.
- [x] Bật billing budget/alert trước khi tạo compute.
- [x] Tạo dev bucket private, versioning và lifecycle rule.
- [x] Tạo Artifact Registry repository.
- [ ] Dùng Cloud Build build image bằng commit SHA, không chỉ dùng tag `latest`.
- [x] Tạo runtime/builder service accounts và cấp quyền tối thiểu theo resource.
- [x] Cloud Build bằng custom builder SA; demo PIT và non-root check pass trước khi publish.

**Hoàn thành khi:** image `<region>-docker.pkg.dev/<project>/pit-feature-store/pipeline:<sha>` tồn tại.

#### 3.4. Cloud Run feasibility spike

- [ ] Upload raw data vào private GCS prefix.
- [x] Mount bucket read/write vào Cloud Run Job hoặc dùng GCS client ở publish layer.
- [ ] Chạy profiling/Bronze/Silver trước.
- [ ] Chạy full PIT feature materialization với `8 vCPU / 32 GiB`, timeout phù hợp.
- [ ] Ghi CPU, peak memory, duration, bytes read/written và chi phí ước tính.

**Go/no-go:** nếu offline job OOM hoặc I/O không ổn định, chưa xây orchestration. Trước hết tối
ưu DuckDB memory/temp strategy hoặc chuyển riêng compute nặng sang phương án khác.

**Đầu ra tuần 3:** một image có version và một manual Cloud Run execution tạo output hợp lệ.

#### Bằng chứng cloud đã xác nhận ngày 2026-11-19

- Cloud Build `583532b6-d303-403b-ae86-f5018a0bb027`: `SUCCESS`, duration `2m34s`.
- Image digest: `sha256:007eb0a769c083efa48b45a6ffad4e2649c8be1b58959530d65e081895efd00d`.
- Cloud Run execution `pit-features-5c8xt`: `1/1` task hoàn thành; future-event demo `PASS`.
- Storage smoke execution `pit-storage-smoke-w2fps`: non-root UID/GID `10001` ghi và đọc lại
  object qua `/mnt/pit-data` thành công.
- Object smoke-test và job tạm đã được xóa sau khi xác minh.
- Còn lại trước khi đóng Mốc 3: Terraform/import hạ tầng, tag image bằng Git commit SHA,
  upload raw data, chạy Bronze/Silver/PIT toàn phần và ghi benchmark chi phí/tài nguyên.

### Tuần 4 — Cloud-safe publish, daily pipeline và backfill

#### 4.1. GCS storage adapter

- [ ] Thêm run-scoped output prefixes.
- [ ] Thêm staging/published/failed manifest states.
- [ ] Thêm catalog pointer và optimistic generation precondition khi cập nhật pointer.
- [ ] Consumer resolve input qua manifest thay vì đoán path mới nhất.
- [ ] Không dùng directory rename làm atomic publish trên GCS.

**Hoàn thành khi:** một job fail sau khi ghi staging không làm consumer thấy output dở.

#### 4.2. Daily incremental contract

- [ ] Mọi job nhận `processing_date` UTC và `run_id`.
- [ ] Ingest chỉ đọc raw partition của ngày được yêu cầu.
- [ ] Silver publish partition ngày tương ứng.
- [ ] PIT job đọc observations ngày mới và đủ history cần thiết.
- [ ] Score job chỉ score ngày mới bằng approved model version.
- [ ] Chạy lại cùng `run_id` không tạo duplicate.

**Hoàn thành khi:** mô phỏng ngày D và D+1 cho kết quả đúng, feature ngày D không đổi khi thêm
future data D+1.

#### 4.3. Backfill contract

- [ ] Workflow nhận `start_date`, `end_date`, `reason` và `requested_by`.
- [ ] Xác định affected observation partitions và history range.
- [ ] Ghi replacement vào run prefix mới.
- [ ] Validate rồi mới cập nhật catalog pointer.
- [ ] Có rollback về manifest trước.
- [ ] Không cho hai backfill cùng feature version/range publish đồng thời.

**Hoàn thành khi:** demo late event được đưa vào backfill nhưng future event vẫn bị loại.

#### 4.4. Workflows và Scheduler

- [ ] Workflows gọi jobs theo thứ tự và truyền cùng `run_id`.
- [ ] Có success/failure branches và retry chỉ cho lỗi transient.
- [ ] Scheduler kích hoạt daily workflow bằng service account riêng.
- [ ] Chống duplicate schedule invocation bằng deterministic run key theo ngày.

**Đầu ra tuần 4:** pipeline daily + backfill chạy được từ một workflow, không publish partial data.

### Tuần 5 — Query, quan sát, kiểm chứng và demo

#### 5.1. BigQuery serving cho demo

- [ ] Tạo dataset cùng location với bucket.
- [ ] Tạo external/managed table cho daily scores, quality summary và run manifest.
- [ ] Viết query kiểm tra số giao dịch, fraud score distribution và top-risk transactions.
- [ ] Không đưa raw sensitive columns không cần thiết vào bảng demo.

#### 5.2. Observability

- [ ] Structured logs theo stage/run/date.
- [ ] Dashboard: success/failure, duration, processed rows, freshness, memory và retry count.
- [ ] Alert: workflow fail, missing raw partition, DQ fail, OOM, runtime vượt ngưỡng.
- [ ] Log retention và exclusion cho log quá chi tiết để kiểm soát chi phí.

Cloud Run tự đưa container/system logs vào Cloud Logging và có Cloud Monitoring metrics. Xem
[Cloud Run monitoring](https://docs.cloud.google.com/run/docs/monitoring).

#### 5.3. Cloud correctness comparison

So sánh cloud với local release `v0.1.0`:

| Kiểm tra | Tiêu chí pass |
|---|---|
| Raw SHA-256 | Giống local |
| Silver row count/unique ID | 1.097.231 / 1.097.231 cho full run |
| Offline row count/unique ID | 1.097.231 / 1.097.231 |
| Training rows | 590.540 |
| Temporal splits | 414.542 / 86.672 / 89.326 |
| Integer/count/time features | Giống tuyệt đối |
| Float sum/average | Absolute difference ≤ `1e-9` |
| Predictions | Giống hoặc nằm trong tolerance đã chốt |
| Evaluation metrics | Khớp báo cáo v1 |
| Future-event demo | PASS |
| Backfill rerun | Không duplicate, catalog chỉ đổi sau validation |

#### 5.4. Demo cuối

```text
1. Upload partition ngày D.
2. Trigger workflow hoặc chờ Scheduler.
3. Xem các stage trong Workflows/Logging.
4. Query daily features và fraud scores bằng BigQuery.
5. Upload partition D+1, chứng minh feature D không đổi.
6. Thêm một late event, backfill D và xem manifest version thay đổi an toàn.
7. Cố tình làm một DQ check fail, chứng minh catalog vẫn trỏ output cũ.
```

**Đầu ra tuần 5:** cloud demo, cloud runbook, cost/runtime report và deployment evidence.

## 6. Thứ tự implementation trong repository

```text
1. docs/GCP_DEPLOYMENT_PLAN.md
2. Dockerfile + .dockerignore
3. configs/cloud/dev.yaml + cloud settings model
4. storage abstraction/local adapter/GCS adapter
5. cloud-safe publish manifest + catalog pointer
6. cloud entrypoint and stage commands
7. infra/terraform foundation
8. cloudbuild.yaml
9. Cloud Run Job definitions
10. workflows/daily_pipeline.yaml
11. BigQuery SQL
12. monitoring/alerts
13. cloud integration tests and runbook
```

Không bắt đầu Workflows trước khi Docker job và cloud publish contract chạy thủ công thành công.

## 7. Testing strategy

### Local tests

- unit tests cho cloud config và URI parsing;
- fake/in-memory storage tests cho manifest state machine;
- retry/idempotency tests;
- concurrent publish conflict test;
- existing 92 regression tests phải tiếp tục pass.

### Cloud integration tests

- image chạy demo nhỏ không cần raw IEEE data;
- write/read test prefix riêng;
- failed run không cập nhật catalog;
- retry cùng run ID không duplicate;
- service account không đọc/ghi ngoài prefix được cấp;
- scheduled workflow nhận đúng `processing_date`.

### Acceptance test

Full cloud run phải đạt bảng tiêu chí ở mục 5.3 trước khi tuyên bố deploy thành công.

## 8. Bảo mật và IAM

- Bucket private, public access prevention bật.
- Mỗi component dùng service account riêng nếu vai trò khác nhau.
- Runtime chỉ có quyền đọc raw và ghi đúng processed/report prefixes cần thiết.
- Scheduler chỉ có quyền invoke Workflow; Workflow chỉ có quyền execute Jobs.
- Cloud Build có quyền push Artifact Registry và deploy tài nguyên đã định.
- Không dùng service-account key JSON nếu workload identity/service identity đáp ứng được.
- Secret Manager chỉ dùng cho secret thật; config thông thường nằm trong versioned YAML/env.

## 9. Quản lý chi phí

- Tạo billing budget và alert trước khi chạy job lớn.
- Chỉ một môi trường `dev` trong MVP.
- Cloud Run Jobs không giữ instance idle.
- Dùng image/version cố định để tránh build lại không cần thiết.
- Lifecycle xóa staging, failed runs và raw demo hết hạn sau thời gian chốt.
- Theo dõi GiB-hours, vCPU-hours, Cloud Storage operations và BigQuery bytes processed.
- Không bật Scheduler tần suất cao trong giai đoạn thử nghiệm.

Không ghi một con số chi phí cố định trong plan vì giá phụ thuộc region, thời gian job, memory,
storage và số lần chạy. Sau feasibility spike phải tạo cost baseline từ billing export/calculator.

## 10. Rủi ro và phương án xử lý

| Rủi ro | Dấu hiệu | Phương án |
|---|---|---|
| Cloud Run OOM | Job bị terminate, memory gần 100% | 32 GiB spike, giảm DuckDB memory, bounded processing |
| GCS FUSE không phù hợp rename | Partial/last-write-wins | Immutable prefixes + manifest pointer |
| Job retry tạo duplicate | Cùng ngày có nhiều output | Deterministic run key, idempotency check |
| Concurrent backfill | Hai writer thay cùng partition | Generation precondition/lock manifest |
| Full run quá chậm | Duration/cost vượt ngưỡng | Tối ưu I/O; đánh giá compute khác cho riêng PIT stage |
| Region không đồng nhất | Egress hoặc BigQuery lỗi location | Một region/location strategy từ đầu |
| Static Kaggle data | Không có daily feed thật | Partition theo event date để mô phỏng |
| Retrain hằng ngày không cần thiết | Tốn chi phí, label chưa có | Tách daily scoring và periodic training |

## 11. Thông tin cần chốt trước khi bắt đầu triển khai

1. GCP project ID và billing account đã sẵn sàng chưa?
2. Region được phép sử dụng là gì? Đề xuất khảo sát `asia-southeast1` và chọn một location
   thống nhất cho Cloud Run, GCS và BigQuery.
3. Mức ngân sách thử nghiệm và ngưỡng cảnh báo?
4. Raw IEEE-CIS có được phép upload vào private bucket của project này không?
5. Dùng Terraform hay chỉ `gcloud`? Plan đề xuất Terraform cho resource, `gcloud` cho thao tác
   debug/manual execution.
6. Demo chỉ cần batch scoring hay cần thêm HTTP API? Plan mặc định batch scoring.

## 12. Definition of Done cho giai đoạn cloud

- Infrastructure có thể dựng lại từ code.
- Image được build, scan và lưu theo commit SHA.
- Manual Cloud Run full run pass.
- Daily workflow và bounded backfill pass.
- Partial/failed output không được publish.
- Logs, dashboard và alert hoạt động.
- BigQuery query xem được daily scores và quality summary.
- Cloud/local correctness comparison đạt tiêu chí.
- Cloud runbook và demo script hoàn chỉnh.
- Chi phí và giới hạn đã được ghi nhận.
