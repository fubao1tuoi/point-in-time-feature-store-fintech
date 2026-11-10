# Golden expected PIT features — manual review

## 1. Mục đích

File `fixtures/golden_expected_features.csv` chứa expected values được tính độc lập cho
10 observations và 20 output columns. Đây là oracle cho PIT engine ở Mốc 5; engine phải
khớp expected, không được dùng để sinh ngược expected.

Quy ước:

- `null` là giá trị null thật, không phải chuỗi model input.
- Count/distinct outputs là integer.
- Amount outputs là numeric và future tests so sánh float bằng tolerance.
- Current row luôn bị loại.
- Lower window boundary inclusive.
- Same timestamp dùng `TransactionID` nhỏ hơn làm history.

## 2. Logical ordering

Input CSV bị xáo physical order, nhưng thứ tự logic là:

```text
101
102 → 103 → 201      (cùng event_time, tăng theo TransactionID)
501
301
401
104
105
106
```

Entity 201 thuộc card B nên không ảnh hưởng card A dù nằm giữa same-time ordering.

## 3. Review theo observation

### ID 101 — no history

Đây là event đầu tiên của secondary card A và primary card A + addr 1:

```text
count/sum/distinct = 0
avg/max/recency    = null
```

Áp dụng giống nhau cho cả hai views.

### ID 102 — inclusive 7-day boundary

ID 101 xảy ra đúng bảy ngày trước ID 102 nên được tính trong window 7 ngày, nhưng nằm
ngoài window 1 giờ và 24 giờ:

```text
count_1h  = 0
count_24h = 0
count_7d  = 1
sum_7d    = 10
max_7d    = 10
distinct_product_7d = 1  (W)
recency   = 7 × 24 × 60 × 60 = 604800 giây
```

Hai views giống nhau tại observation này.

### ID 103 — same timestamp

ID 102 có cùng `event_time` nhưng ID nhỏ hơn, nên được dùng; ID 103 hiện tại bị loại.
ID 101 vẫn nằm trong window 7 ngày:

```text
1h/24h history = [102]
7d history     = [101, 102]

count_1h  = 1
sum_1h    = 20
count_7d  = 2
sum_7d    = 10 + 20 = 30
avg_24h   = 20
max_7d    = 20
recency   = 0 giây
distinct_product_7d = 2  (W, C)
```

### ID 201 — entity isolation

ID 201 thuộc card B/card B + addr 1. Các rows của card A không được dùng, nên cả hai
views có no-history defaults. Amount 999 của ID 201 cũng không được đi vào output của
các observation card A trước nó; các observation card A sau nó vẫn loại ID 201 vì khác
entity.

### ID 501 — same secondary, different primary

ID 501 dùng secondary card A nhưng primary card A + addr 2:

```text
Primary history   = []
Secondary bounded history = [102, 103]
```

ID 101 cách observation hơn bảy ngày 10 phút nên ngoài các bounded windows. Previous
secondary event gần nhất ở 00:00, cách 600 giây.

```text
primary count/sum/distinct = 0; avg/max/recency = null
secondary count = 2
secondary sum   = 20 + 30 = 50
secondary avg   = 25
secondary max   = 30
secondary recency = 600
secondary distinct products = 2  (C, H)
```

### ID 301 — null primary, secondary available

Primary entity null nên toàn bộ `card_addr_*` bằng null, không phải 0.

Secondary bounded history:

```text
[102, 103, 501]
```

```text
count = 3
sum   = 20 + 30 + 60 = 110
avg   = 110 / 3 = 36.6666666667
max   = 60
recency = 5 phút = 300 giây
distinct products = 2  (C, H)
```

### ID 401 — null both entities

Cả `card_entity_id` và `card_address_entity_id` đều null, nên toàn bộ 20 outputs bằng
null. Amount/Product của row không được dùng để tự tạo entity hoặc history.

### ID 104 — null amount và product

Current ID 104 chưa đi vào feature của chính nó. Primary bounded history là `[102, 103]`:

```text
primary count = 2
primary sum   = 50
primary avg   = 25
primary max   = 30
primary recency = 30 phút = 1800 giây
primary distinct products = 2  (C, H)
```

Secondary bounded history là `[102, 103, 501, 301]`:

```text
secondary count = 4
secondary sum   = 20 + 30 + 60 + 40 = 150
secondary avg   = 150 / 4 = 37.5
secondary max   = 60
secondary recency = 15 phút = 900 giây
secondary distinct products = 3  (C, H, S)
```

Null amount/product của 104 chỉ ảnh hưởng các observation sau: row vẫn được count và có
thể là previous transaction, nhưng bị bỏ qua trong amount/product aggregates.

### ID 105 — inclusive 1-hour boundary

Observation lúc 01:00; IDs 102/103 lúc 00:00 nằm đúng lower boundary và được tính.

Primary history trong các bounded windows là `[102, 103, 104]`:

```text
count = 3
sum   = 20 + 30 = 50       (104 amount null)
avg   = 25
max   = 30
recency = 30 phút = 1800 giây
distinct products = 2      (104 product null)
```

Secondary history là `[102, 103, 501, 301, 104]`:

```text
count = 5
sum   = 20 + 30 + 60 + 40 = 150
avg   = 150 / 4 = 37.5
max   = 60
recency = 30 phút = 1800 giây
distinct products = 3  (C, H, S)
```

### ID 106 — inclusive 24-hour boundary

Observation lúc 09/01 00:00; IDs 102/103 đúng 24 giờ trước nên được tính trong 24h.
Không có event trong một giờ gần nhất:

```text
count_1h = 0
sum_1h   = 0
```

Primary 24h/7d history là `[102, 103, 104, 105]`:

```text
count = 4
sum   = 20 + 30 + 70 = 120
avg_24h = 120 / 3 = 40
max_7d  = 70
recency = 23 giờ = 82800 giây
distinct products = 3  (C, H, R)
```

Secondary 24h/7d history là `[102, 103, 501, 301, 104, 105]`:

```text
count = 6
sum   = 20 + 30 + 60 + 40 + 70 = 220
avg_24h = 220 / 5 = 44
max_7d  = 70
recency = 82800 giây
distinct products = 4  (C, H, S, R)
```

## 4. Future-event proof encoded by expected rows

Expected output của một observation chỉ dùng IDs đứng trước nó theo tuple. Ví dụ:

- Output 102 không chứa 103/104/105/106.
- Output 103 không chứa 501/301/104/105/106.
- Output 104 không chứa 105/106.

Khi Mốc 5 triển khai engine, append-only invariance test sẽ thêm future rows và xác nhận
expected outputs của past observations không đổi.

## 5. Review checklist

- [x] No-history defaults phân biệt 0 và null.
- [x] 1h/24h/7d lower boundaries inclusive.
- [x] Same timestamp dùng lower `TransactionID`.
- [x] Current event không tự count/sum.
- [x] Future rows không xuất hiện trong past expected values.
- [x] Entity B không trộn với entity A.
- [x] Primary và secondary grains được tách.
- [x] Null entity trả null cho cả view.
- [x] Null amount/product bị bỏ qua đúng aggregation.
- [x] Physical input order không được dùng làm time order.
