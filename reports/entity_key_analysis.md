# Surrogate Entity Key Analysis

> Sinh tự động lúc `2026-11-03T05:21:53.718843+00:00` từ `train_transaction.csv`.

## 1. Mục tiêu

IEEE-CIS không cung cấp customer/account ID. Phân tích này so sánh các tổ hợp card/address/email để chọn một surrogate entity dùng cho rolling historical features.
Surrogate entity chỉ là khóa phân nhóm phục vụ nghiên cứu, không phải danh tính thật.

## 2. Chính sách phân tích

- **Strict complete case:** transaction thiếu bất kỳ thành phần nào của candidate sẽ không được gán entity cho candidate đó.
- **Exact tuple match:** hai transaction cùng entity khi toàn bộ giá trị trong tổ hợp bằng nhau.
- `isFraud` chỉ dùng chẩn đoán sau khi tạo entity, tuyệt đối không tham gia công thức key.

## 3. Vì sao cần từng metric?

### Assigned transaction coverage

Tỷ lệ transaction có đủ tất cả thành phần để tạo key. Coverage thấp làm nhiều transaction không có historical features. Đây là chi phí trực tiếp của việc thêm cột vào key.

### Unique entities

Số nhóm được tạo. Quá ít entity cho thấy key quá rộng và có nguy cơ gom nhiều người/thẻ; quá nhiều entity có thể cho thấy key quá hẹp và phá vỡ lịch sử thành nhiều mảnh.

### Transactions per entity: mean, median và quantiles

Đo độ sâu lịch sử của entity. Median cho entity điển hình; P95/P99 cho phần đuôi; maximum giúp phát hiện nhóm bất thường. Mean đơn lẻ có thể bị entity rất lớn làm sai lệch.

### Singleton entity rate

Tỷ lệ entity chỉ xuất hiện một lần. Singleton không có transaction trước đó, vì vậy không tạo được velocity, recency hay rolling aggregates tại lần xuất hiện duy nhất.

### Repeat transaction coverage

Tỷ lệ transaction nằm trong entity có ít nhất hai giao dịch. Đây là metric trực tiếp nhất cho biết bao nhiêu transaction có khả năng hưởng lợi từ historical features. Báo cáo có cả coverage trên assigned transactions và trên toàn dataset.

### Entity skew

Tỷ trọng transaction thuộc top 10 và top 1% entity. Skew quá cao có thể nghĩa key gom nhiều đối tượng khác nhau, hoặc tạo hotspot làm rolling computation tốn bộ nhớ.

### Temporal span của repeated entities

Khoảng cách giữa transaction đầu và cuối. Entity lặp lại nhưng chỉ trong vài phút không hữu ích cho window 7/30 ngày. P50/P95 span cho biết candidate hỗ trợ được time horizon nào.

### Label diagnostics

Fraud rate, entity có fraud và mixed-label entity giúp hiểu candidate có gom các transaction liên quan theo labeling logic hay không. Các metric này chỉ dùng chẩn đoán; dùng label để tạo key sẽ gây target leakage.

## 4. So sánh candidate keys

| Candidate | Components | Assigned % | Entities | Singleton % | Repeat coverage overall % | Median tx/entity | P95 | Max |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `card1` | `card1` | 100.00 | 13,553 | 25.41 | 99.42 | 4.00 | 107.00 | 14,932 |
| `card1_addr1` | `card1+addr1` | 88.87 | 37,531 | 39.48 | 86.36 | 2.00 | 45.00 | 5,885 |
| `card_attributes` | `card1+card2+card3+card5` | 98.13 | 13,656 | 25.43 | 97.54 | 4.00 | 104.00 | 14,112 |
| `card_attributes_addr1` | `card1+card2+card3+card5+addr1` | 87.15 | 38,145 | 39.42 | 84.60 | 2.00 | 43.00 | 5,866 |
| `card_attributes_addr1_email` | `card1+card2+card3+card5+addr1+P_emaildomain` | 71.84 | 73,747 | 49.85 | 65.61 | 2.00 | 19.00 | 2,236 |

## 5. Coverage và null trade-off

| Candidate | Assigned transactions | Incomplete transactions | Incomplete % | Repeat coverage assigned % |
|---|---:|---:|---:|---:|
| `card1` | 590,540 | 0 | 0.00 | 99.42 |
| `card1_addr1` | 524,834 | 65,706 | 11.13 | 97.18 |
| `card_attributes` | 579,507 | 11,033 | 1.87 | 99.40 |
| `card_attributes_addr1` | 514,655 | 75,885 | 12.85 | 97.08 |
| `card_attributes_addr1_email` | 424,240 | 166,300 | 28.16 | 91.33 |

## 6. Entity skew

| Candidate | Top 10 share % | Top 1% share % | P99 tx/entity |
|---|---:|---:|---:|
| `card1` | 15.22 | 52.97 | 786.44 |
| `card1_addr1` | 7.00 | 39.96 | 194.00 |
| `card_attributes` | 14.55 | 52.34 | 735.90 |
| `card_attributes_addr1` | 7.12 | 39.86 | 187.56 |
| `card_attributes_addr1_email` | 3.51 | 30.86 | 66.00 |

## 7. Temporal span của repeated entities

| Candidate | P50 days | P90 days | P95 days | Max days |
|---|---:|---:|---:|---:|
| `card1` | 132.70 | 177.99 | 180.39 | 181.99 |
| `card1_addr1` | 110.01 | 174.83 | 178.91 | 181.98 |
| `card_attributes` | 126.93 | 177.85 | 180.27 | 181.99 |
| `card_attributes_addr1` | 98.04 | 174.16 | 178.75 | 181.98 |
| `card_attributes_addr1_email` | 75.80 | 166.43 | 174.21 | 181.97 |

## 8. Label diagnostics — không dùng để tạo key

| Candidate | Fraud rate assigned % | Entities with fraud % | Mixed-label entities % | Fraud in repeated entities % |
|---|---:|---:|---:|---:|
| `card1` | 3.50 | 12.84 | 11.34 | 99.29 |
| `card1_addr1` | 2.46 | 8.13 | 6.30 | 96.30 |
| `card_attributes` | 3.46 | 12.81 | 11.37 | 99.30 |
| `card_attributes_addr1` | 2.45 | 7.92 | 6.13 | 96.22 |
| `card_attributes_addr1_email` | 2.40 | 4.86 | 3.06 | 91.24 |

## 9. Cách ra quyết định

Không chọn candidate chỉ vì có nhiều entity hoặc nhiều transaction/entity nhất. Candidate phù hợp phải cân bằng:

1. Coverage đủ cao để phần lớn transaction có entity.
2. Repeat coverage đủ cao để rolling features có giá trị.
3. Singleton rate không quá lớn.
4. Top-entity concentration không bất thường.
5. Temporal span phù hợp với các window 1 ngày, 7 ngày và 30 ngày.
6. Thành phần key có lý do nghiệp vụ hợp lý và tương đối ổn định.

Kết quả này không thể chứng minh candidate tương ứng chính xác với customer/card thật. Quyết định cuối cùng phải được ghi là một modeling assumption.

Profiling runtime: **16.14 giây**.
