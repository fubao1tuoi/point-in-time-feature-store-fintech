# Test strategy

- `unit/`: logic đơn lẻ và deterministic transformations.
- `integration/`: pipeline chạy qua nhiều layer.
- `data_quality/`: schema, uniqueness, null và accepted values.
- `point_in_time/`: cutoff, window boundary, same timestamp và leakage tests.

