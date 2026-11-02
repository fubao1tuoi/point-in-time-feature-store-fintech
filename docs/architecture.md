# Architecture

Kiến trúc chi tiết sẽ được hoàn thiện sau khi chốt processing engine trong tuần 1.

Luồng mục tiêu:

```text
Kaggle CSV → Bronze → Silver → PIT feature computation
                              ├─→ Offline feature store → Training dataset
                              └─→ Online store/API (optional)
```

