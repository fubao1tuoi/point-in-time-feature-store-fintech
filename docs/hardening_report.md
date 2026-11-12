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
