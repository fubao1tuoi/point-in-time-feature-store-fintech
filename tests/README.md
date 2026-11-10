# Test strategy

- `unit/`: logic đơn lẻ và deterministic transformations.
- `integration/`: pipeline chạy qua nhiều layer.
- `data_quality/`: schema, uniqueness, null và accepted values.
- `point_in_time/`: cutoff, window boundary, same timestamp và leakage tests.

## Feature Registry invalid-file exercise

`fixtures/feature_registry_invalid_demo.yaml` là file demo cố ý sai ở window đầu tiên:

```yaml
window: 1hour
```

Chạy validator với file demo làm primary registry:

```powershell
python pipelines/validate_feature_registry.py `
  --primary tests/fixtures/feature_registry_invalid_demo.yaml `
  --secondary configs/features/transaction_velocity_card_v1.yaml
```

Lần đầu phải fail với exit code 1. Sửa `1hour` thành `1h`, chạy lại cùng lệnh thì phải
pass và báo 20 output columns. Sau khi thử xong, đổi lại `1hour` để giữ đây là negative
demo fixture. Không sửa registry production trong `configs/features/`.

