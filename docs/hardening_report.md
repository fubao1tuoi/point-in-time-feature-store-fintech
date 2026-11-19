# Mốc 8 — Leakage audit, tối ưu và hardening

## 1. Leakage audit

Audit tự động chạy 17 checks và tất cả đều pass:

- primary/secondary dùng strict cutoff `(event_time, TransactionID) < observation tuple`;
- current transaction bị loại;
- `isFraud` không tham gia công thức feature;
- preprocessing artifact chỉ fit trên train và kết thúc trước validation boundary;
- train, validation và internal test không overlap;
- training dataset không duplicate và không thiếu PIT join.

Future-invariance và late-event semantics còn được kiểm tra bằng executable tests, không chỉ
dựa vào nội dung YAML.

## 2. Edge cases

`tests/point_in_time/test_hardening_edge_cases.py` kiểm tra:

- **null entity:** observation được giữ, feature view tương ứng là null;
- **skew:** một entity có 201 events vẫn cho count/sum chính xác và không duplicate output;
- **same timestamp:** ID nhỏ hơn được xem là history, ID lớn hơn không đi ngược về quá khứ;
- **late arrival:** event được append muộn nhưng có event time cũ sẽ xuất hiện sau backfill;
- **future event:** event time sau observation không làm thay đổi past features.

## 3. Tối ưu bounded backfill

Tối ưu được áp dụng khi có `start_time/end_time`:

1. observation filter giới hạn time range, cho phép DuckDB predicate/partition pruning;
2. future history sau maximum prediction time bị loại;
3. history semi-join với các primary/secondary entities thực sự xuất hiện trong batch;
4. full initial build không materialize hai bản history không cần thiết.

Có thể tắt để đối chứng:

```powershell
python pipelines/materialize_offline_features.py `
  --backfill `
  --start-time "2017-01-08T00:00:00Z" `
  --end-time "2017-01-09T00:00:00Z" `
  --disable-history-optimization
```

## 4. Benchmark trước và sau

Controlled benchmark gồm 5.000 history rows và 144 observations:

| Chỉ số | Baseline | Optimized |
|---|---:|---:|
| Logical history candidates | 10.000 | 1.440 |
| Candidate reduction | — | **85,6%** |
| Runtime nhỏ | 0,114 s | 0,179 s |

Tối ưu giảm mạnh lượng history candidate nhưng micro-benchmark nhỏ chạy chậm hơn do chi phí
tạo hai reduced history tables. Vì vậy kết quả không được mô tả sai là runtime speedup. Giá
trị chính ở bounded backfill lớn là giảm intermediate/history volume; benchmark production
scale vẫn cần thực hiện trước khi tuning heuristic tiếp theo.

### Giải thích dễ hiểu các con số

`5.000` là số giao dịch giả lập được tạo tạm trong DuckDB để benchmark, không phải một phần
của IEEE-CIS và không được lưu thành CSV/Parquet. Các giao dịch cách nhau 10 phút nên 5.000
dòng tạo ra khoảng 34,7 ngày lịch sử, đủ để thử các window 1 giờ, 24 giờ và 7 ngày.

Khoảng backfill dài đúng một ngày. Với một giao dịch mỗi 10 phút, ngày đó có:

```text
24 giờ × 6 giao dịch/giờ = 144 observations
```

Baseline chuẩn bị toàn bộ 5.000 history rows cho primary entity view và thêm 5.000 rows cho
secondary view. Vì cùng một source được xét theo hai entity views nên báo cáo ghi `10.000
logical history candidates`; dataset vẫn chỉ có 5.000 giao dịch.

Trong ngày backfill, 144 observations thuộc 144 entity liên quan. Mỗi entity này xuất hiện 5
lần trong phần lịch sử trước cutoff, nên history đã lọc còn:

```text
Primary:   144 entity × 5 rows = 720 candidates
Secondary: 144 entity × 5 rows = 720 candidates
Tổng:                             1.440 candidates
```

Pipeline không xóa dữ liệu nguồn. Nó chỉ không đưa history của entity chắc chắn không liên
quan, hoặc event nằm sau observation cuối cùng, vào bảng trung gian. Sau bước lọc thô, PIT
predicate vẫn kiểm tra cùng entity, time window, current-event và future-event cho từng
observation.

```text
1 - 1.440 / 10.000 = 85,6% candidate reduction
```

Hai cách đều tạo 144 feature rows và `different rows = 0`. Con số 85,6% vì vậy chỉ chứng minh
giảm dữ liệu trung gian trong micro-benchmark này, không có nghĩa pipeline production luôn
nhanh hơn 85,6%. Thực tế runtime nhỏ tăng từ 0,114 lên 0,179 giây vì chi phí tạo bảng lọc và
semi-join lớn hơn lợi ích trên dataset chỉ có 5.000 dòng.

### Dữ liệu giả lập nằm ở đâu?

Dữ liệu được tạo bởi `_create_benchmark_source()` trong `src/pit_feature_store/hardening.py`
từ cấu hình `configs/hardening.yaml`:

```yaml
source_rows: 5000
entity_count: 1000
seconds_between_events: 600
start_time: "2017-01-31T00:00:00Z"
end_time: "2017-02-01T00:00:00Z"
```

Hàm tạo `TEMP TABLE silver_transactions` trong DuckDB in-memory. Bảng 5.000 dòng chỉ tồn tại
trong lúc `python pipelines/run_hardening_audit.py` chạy và tự biến mất khi process kết thúc.
Repository lưu công thức tạo dữ liệu và kết quả benchmark, không lưu thêm một dataset giả lập.

## 5. Chứng minh tương đương

Baseline và optimized được chạy trên cùng input/range. So sánh hai chiều bằng `EXCEPT ALL`:

```text
different rows = 0
baseline fingerprint = rows=144;xor64=15121308383017031769
optimized fingerprint = rows=144;xor64=15121308383017031769
```

Như vậy tối ưu chỉ thay đổi phạm vi dữ liệu trung gian, không thay đổi feature output.

## 6. Audit log và failure handling

Output:

```text
reports/generated/hardening/v1/
  hardening_report.json
  audit_log.jsonl
```

Mỗi stage ghi `started/success/failed`, duration và UTC timestamp rồi flush ngay xuống JSONL.
Nếu run fail:

- staging không được publish thành `vN`;
- error type/message/traceback được ghi;
- audit log được giữ tại `reports/generated/hardening/failures/`;
- bounded backfill partition publish vẫn dùng backup/rollback hiện có.

## 7. Cách chạy

```powershell
cd "D:\AITC VinUni\Fintech project"
& ".\.venv\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip install -e ".[dev]"
python pipelines/run_hardening_audit.py
```

Thành công khi thấy:

```text
[hardening] success: reports\generated\hardening\v1
```

Hardening v1 đã tồn tại trên máy hiện tại và là immutable.
