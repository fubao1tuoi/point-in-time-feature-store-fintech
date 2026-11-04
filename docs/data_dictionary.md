# Data Dictionary — IEEE-CIS Fraud Detection

> Tài liệu này giải thích cấu trúc và ý nghĩa **được công bố** của bộ dữ liệu IEEE-CIS Fraud Detection. Nhiều trường đã được Vesta ẩn danh; với các trường đó, tài liệu chỉ mô tả đúng ở cấp nhóm và không suy đoán ý nghĩa cụ thể.

## 1. Tổng quan dataset

Bộ dữ liệu mô tả các giao dịch thương mại điện tử do Vesta cung cấp cho cuộc thi IEEE-CIS Fraud Detection trên Kaggle. Transaction table không chỉ đại diện cho việc chuyển tiền hoặc mua một món hàng vật lý. Theo giải thích của host, transaction có thể liên quan tới hàng hóa, quà tặng hoặc dịch vụ, ví dụ một người đặt vé/dịch vụ cho người khác. Nhiệm vụ gốc là dự đoán xác suất một transaction được gắn nhãn `isFraud`.

Dataset được tách thành hai loại bảng:

- **Transaction:** thông tin giao dịch, thanh toán, thẻ, địa chỉ, email và các feature đã được Vesta tạo sẵn.
- **Identity:** thông tin liên quan đến thiết bị, kết nối và digital identity của phiên giao dịch.

Hai bảng được nối bằng `TransactionID`:

```text
transaction LEFT JOIN identity USING (TransactionID)
```

Phải dùng `LEFT JOIN` vì không phải giao dịch nào cũng có identity record.

## 2. Các file dữ liệu

| File | Số dòng | Số cột | Nội dung |
|---|---:|---:|---|
| `train_transaction.csv` | 590.540 | 394 | Transaction data và nhãn `isFraud`. |
| `train_identity.csv` | 144.233 | 41 | Identity/device data của một phần train transactions. |
| `test_transaction.csv` | 506.691 | 393 | Transaction data dùng cho Kaggle test, không có nhãn. |
| `test_identity.csv` | 141.907 | 41 | Identity/device data của một phần test transactions. |
| `sample_submission.csv` | 506.691 | 2 | Mẫu submission gồm `TransactionID` và xác suất `isFraud`. |

Identity coverage từ dữ liệu thực tế:

- Train: khoảng **24,42%** transaction có identity record.
- Test: khoảng **28,01%** transaction có identity record.

## 3. Mức độ hiểu biết về các cột

Không phải cột nào trong dataset cũng có thể diễn giải về mặt nghiệp vụ.

| Mức | Ý nghĩa |
|---|---|
| **Rõ** | Kaggle công bố trực tiếp ý nghĩa, ví dụ `TransactionAmt`. |
| **Biết theo nhóm** | Biết nhóm nghiệp vụ nhưng không biết mapping từng cột, ví dụ `card1`–`card6`. |
| **Ẩn danh** | Chỉ biết đây là feature do Vesta tạo, không biết công thức hoặc semantics, ví dụ `V1`–`V339`. |

Nguyên tắc của project:

> Không tự gán ý nghĩa nghiệp vụ cụ thể cho cột đã bị ẩn danh nếu nguồn dữ liệu không công bố ý nghĩa đó.

---

## 4. Các cột lõi của transaction table

| Cột | Kiểu khái niệm | Ý nghĩa | Lưu ý trong project |
|---|---|---|---|
| `TransactionID` | Identifier | Định danh duy nhất của một transaction. | Dùng để join transaction với identity; không phải customer ID. |
| `isFraud` | Target | `1` nếu transaction được gắn nhãn gian lận, `0` nếu không. | Chỉ có trong train; không được dùng để tạo feature đầu vào. |
| `TransactionDT` | Relative time | Số giây tính từ một mốc thời gian tham chiếu không được công bố. | Không phải Unix timestamp hoặc ngày giờ thật. Đây là time column chính cho PIT. |
| `TransactionAmt` | Numeric amount | Giá trị thanh toán của transaction, đơn vị USD theo mô tả của host. | Có thể dùng trực tiếp cho current transaction và làm nguồn rolling aggregates. |
| `ProductCD` | Categorical | Product code — mã sản phẩm của từng transaction. | Có 5 giá trị trong dữ liệu; ý nghĩa từng mã sản phẩm không được công bố. |

### 4.1. Danh sách categorical features chính thức

Competition host xác nhận các transaction features sau là categorical:

```text
ProductCD
card1, card2, card3, card4, card5, card6
addr1, addr2
P_emaildomain, R_emaildomain
M1, M2, M3, M4, M5, M6, M7, M8, M9
```

Identity categorical features:

```text
DeviceType, DeviceInfo
id_12, id_13, ..., id_38
```

Điều này có nghĩa các cột như `card1`, `card2`, `addr1` hoặc `id_12` không nên được coi là continuous measurements chỉ vì CSV lưu chúng bằng số. Khi dùng cho model, chúng cần được xử lý như category/code.

### 4.2. `TransactionID`

Kết quả profiling:

- Không có null.
- Không có duplicate trong từng bảng transaction/identity.
- Mỗi transaction có một `TransactionID` riêng.

Vai trò:

- Join transaction và identity.
- Deduplication.
- Truy vết record.
- Làm tie-breaker kỹ thuật nếu project cần xử lý các transaction có cùng `TransactionDT`.

Không dùng `TransactionID` làm entity cho rolling history vì mỗi transaction gần như có ID riêng.

### 4.3. `isFraud`

Phân bố trong train:

| Nhãn | Số lượng | Tỷ lệ |
|---|---:|---:|
| `0` — non-fraud | 569.877 | 96,501% |
| `1` — fraud | 20.663 | 3,499% |

Dataset mất cân bằng, vì vậy accuracy không phải metric chính. Project nên dùng ROC-AUC, PR-AUC và các metric vận hành như Recall@FPR hoặc Precision@K.

### 4.4. `TransactionDT`

`TransactionDT` có đơn vị giây. Dữ liệu train có phạm vi:

```text
86.400 → 15.811.131 giây
```

Giá trị đầu tiên là `86.400`, đúng bằng số giây trong một ngày. Giá trị lớn nhất là `15.811.131`, tương ứng gần ngày thứ 183 tính từ mốc tham chiếu. Vì vậy train data trải dài khoảng sáu tháng, với 182 relative-day buckets quan sát được trong profiler.

Project sẽ tạo timestamp kỹ thuật:

```text
event_time = synthetic_epoch + TransactionDT seconds
```

`synthetic_epoch` chỉ là mốc giả lập để hỗ trợ windowing và partitioning. Không được trình bày nó như ngày giao dịch thật.

### 4.5. `TransactionAmt`

Tên cột thực tế trong CSV là `TransactionAmt`. Một số mô tả trong discussion viết `TransactionAMT`; hai cách viết này cùng chỉ một trường, nhưng code phải dùng đúng `TransactionAmt` theo header thực tế.

Train có phạm vi quan sát được:

```text
0,251 → 31.937,391
```

Theo mô tả của competition host, đây là **transaction payment amount in USD**. Vì vậy project có thể diễn giải `TransactionAmt` là số tiền thanh toán bằng USD. Dataset không công bố thêm chi tiết như phí, thuế, hoàn tiền hoặc quy trình quy đổi ngoại tệ.

Một số amount có ba chữ số sau dấu thập phân và có hiện tượng đồng thời thiếu `addr1`, `addr2`. Có giả thuyết rằng đây có thể là kết quả quy đổi từ ngoại tệ sang USD, nhưng phần mô tả hiện có **không xác nhận** giả thuyết đó. Project không được dùng số chữ số thập phân để kết luận một transaction là foreign transaction nếu chưa có kiểm chứng bổ sung.

Ứng dụng của `TransactionAmt` trong PIT features:

- `amount_sum_1h`, `amount_sum_24h`, `amount_sum_7d`.
- `amount_avg_7d`.
- `amount_max_7d`.
- Tỷ lệ current amount so với lịch sử của entity.

### 4.6. `ProductCD`

`ProductCD` là product code của transaction. Theo clarification của host, “product” không bắt buộc là một món hàng vật lý hoặc item được thêm vào shopping cart; nó có thể đại diện cho một loại dịch vụ.

Dataset có năm mã `ProductCD`, nhưng không công bố tên hoặc ý nghĩa nghiệp vụ của từng mã. Vì vậy project xử lý đây là categorical feature, không tự đặt nhãn sản phẩm/dịch vụ cho từng code.

---

## 5. Nhóm thông tin thẻ: `card1`–`card6`

Theo mô tả từ competition host, nhóm này chứa thông tin payment card, chẳng hạn:

- Card type.
- Card category.
- Issuing bank.
- Country.

Dataset không công bố mapping chính xác giữa `card1`–`card6` và từng khái niệm trên. Vì vậy có thể khẳng định ý nghĩa ở cấp nhóm, nhưng không được khẳng định riêng `card1` là loại thẻ hay `card3` là quốc gia.

| Cột | Kiểu quan sát | Cardinality train | Null train | Cách hiểu an toàn |
|---|---|---:|---:|---|
| `card1` | Numeric categorical | 13.553 | 0,00% | Mã thẻ/nhóm thẻ đã ẩn danh; candidate tốt để phân nhóm entity. |
| `card2` | Numeric categorical | 500 | 1,51% | Thuộc tính thẻ đã mã hóa. |
| `card3` | Numeric categorical | 114 | 0,27% | Thuộc tính thẻ đã mã hóa. |
| `card4` | String categorical | 4 | 0,27% | Thuộc tính phân loại thẻ; không cần one-hot quá lớn. |
| `card5` | Numeric categorical | 119 | 0,72% | Thuộc tính thẻ đã mã hóa. |
| `card6` | String categorical | 4 | 0,27% | Thuộc tính phân loại thẻ. |

Competition host xếp **toàn bộ `card1`–`card6` vào categorical features**, kể cả những cột đang được lưu bằng số.

Lưu ý:

- Numeric representation không có nghĩa đây là continuous numeric feature.
- Không nên cộng, lấy trung bình hoặc diễn giải khoảng cách giữa các mã `card*`.
- Có thể dùng để xây surrogate entity, nhưng phải đánh giá singleton rate và entity skew.

Ví dụ candidate entity:

```text
hash(card1, card2, card3, card5, addr1)
```

Đây chỉ là khóa phân nhóm phục vụ nghiên cứu, không phải danh tính chủ thẻ thật.

---

## 6. Nhóm địa chỉ: `addr1`, `addr2`

Theo clarification của competition host, cả hai địa chỉ thuộc về purchaser:

- `addr1`: billing region.
- `addr2`: billing country.

Cả hai là categorical features và giá trị đã được mã hóa.

| Cột | Ý nghĩa được công bố | Cardinality train | Null train |
|---|---|---:|---:|
| `addr1` | Billing region của purchaser, đã được mã hóa. | 332 | 11,13% |
| `addr2` | Billing country của purchaser, đã được mã hóa. | 74 | 11,13% |

Ứng dụng:

- Thành phần của surrogate entity.
- Phân tích thay đổi địa chỉ theo lịch sử.
- Tạo feature “địa chỉ đã từng xuất hiện với entity hay chưa”.

Không được suy ra tên region, country hoặc địa chỉ thật từ các mã nếu không có mapping.

---

## 7. Nhóm khoảng cách: `dist1`, `dist2`

Competition host mô tả `dist` là **distance** giữa các tín hiệu có thể gồm, nhưng không giới hạn ở:

- Billing address.
- Mailing address.
- ZIP/postal code.
- IP address.
- Phone area.

Không có mapping cho biết riêng `dist1`, `dist2` đo cặp tín hiệu nào, cũng không công bố đơn vị và công thức chi tiết.

| Cột | Kiểu | Lưu ý |
|---|---|---|
| `dist1` | Numeric | Có thể sử dụng như raw numeric feature sau khi kiểm tra distribution. |
| `dist2` | Numeric | Missing khoảng 93,63% trong train; không nên là feature MVP ưu tiên. |

Không nên gán riêng `dist1` là khoảng cách địa lý hoặc `dist2` là khoảng cách IP khi chưa có pairwise mapping.

---

## 8. Nhóm email domain

| Cột | Ý nghĩa | Cardinality train | Null train |
|---|---|---:|---:|
| `P_emaildomain` | Email domain của purchaser. | 59 | 15,99% |
| `R_emaildomain` | Email domain của recipient. | 60 | 76,75% |

Một số transaction không có recipient, vì vậy `R_emaildomain` có thể null theo đúng nghiệp vụ chứ không nhất thiết là lỗi thu thập dữ liệu.

Ứng dụng:

- Current-transaction categorical feature.
- Thành phần tùy chọn của surrogate entity.
- Feature domain “đã từng thấy trước đây” hoặc số domain khác nhau trong lịch sử.

Do `R_emaildomain` thiếu nhiều, cần giữ null semantics hoặc thêm `has_recipient_email` thay vì tự động biến null thành một domain thật.

---

## 9. Nhóm counting features: `C1`–`C14`

Danh sách:

```text
C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14
```

Theo mô tả của Vesta, đây là các **counting features**. Ví dụ được host đưa ra là số lượng địa chỉ được tìm thấy có liên hệ với payment card. Clarification bổ sung cho biết các phép đếm có thể liên quan tới:

- Phone number.
- Email address.
- Name.
- Device.
- IP address.
- Billing address.

Các phép đếm có thể áp dụng cho cả purchaser và recipient, làm tăng số nhóm count feature. Tuy nhiên, pairwise meaning của từng `C1`–`C14` vẫn bị che giấu.

Phân loại sử dụng:

- Có thể dùng trong model baseline mở rộng.
- Không dùng làm ví dụ chính để giải thích PIT correctness vì không biết window và công thức tạo.
- Cần kiểm tra distribution, outlier và temporal drift.
- Không khẳng định các cột này an toàn khỏi leakage nếu không biết thời điểm nguồn được tổng hợp.

---

## 10. Nhóm timedelta features: `D1`–`D15`

Danh sách:

```text
D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13, D14, D15
```

Đây là các **timedelta features**. Ví dụ được host đưa ra là số ngày kể từ transaction trước đó. Tuy nhiên, không có pairwise mapping cho biết từng `D1`–`D15` đo khoảng thời gian giữa những sự kiện cụ thể nào.

Lưu ý:

- `D7` thiếu khoảng 93,41% trong train.
- Một số `D` có thể mang tín hiệu thời gian mạnh nhưng không thể dùng để minh họa logic business cụ thể.
- Phải phân biệt `D1`–`D15` với `TransactionDT`: `TransactionDT` là trục thời gian chung; `D*` là các feature thời gian ẩn nghĩa.
- Không dùng `D*` làm cutoff time của PIT Join.

---

## 11. Nhóm match features: `M1`–`M9`

Danh sách:

```text
M1, M2, M3, M4, M5, M6, M7, M8, M9
```

Đây là các **match features**. Ví dụ được host đưa ra là kiểm tra sự khớp giữa tên trên thẻ và địa chỉ. Mapping chính xác của từng `M1`–`M9` không được công bố.

Competition host xác nhận **`M1`–`M9` là categorical features**.

Đặc điểm thường gặp:

- Giá trị mang tính boolean/categorical.
- Có missing values.
- Có thể dùng làm raw features trong baseline model.

Không nên đổi tên thành một ý nghĩa cụ thể như `name_matches_card` nếu chưa có mapping chính thức.

---

## 12. Nhóm engineered features: `V1`–`V339`

Danh sách đầy đủ là dải liên tục:

```text
V1, V2, ..., V339
```

Đây là nhóm **Vesta engineered rich features**, bao gồm:

- Ranking features.
- Counting features.
- Các feature mô tả những quan hệ entity khác.

Ví dụ được host đưa ra: số lần một payment card xuất hiện cùng IP, email hoặc address trong một cửa sổ 24 giờ. Đây là ví dụ về kiểu quan hệ có thể được mã hóa, không phải mapping cho một cột `V` cụ thể.

Host cho biết toàn bộ Vesta features được tạo dưới dạng numerical. Một số là số order trong cluster, time window hoặc điều kiện nhất định, nên có tính hữu hạn và có ordering/ranking. Vì vậy:

- Mặc định xử lý `V1`–`V339` như numerical features.
- Không chuyển chúng thành categorical chỉ vì cardinality quan sát được thấp.
- Nếu một cột tình cờ chỉ có hai giá trị, có thể thử như binary feature nhưng phải ghi đây là quyết định thực nghiệm.

Ý nghĩa và công thức của từng `V1`–`V339` đã bị ẩn. Dataset không công bố:

- Ý nghĩa nghiệp vụ.
- Công thức tính.
- Nguồn dữ liệu gốc.
- Cửa sổ thời gian.
- Null/default semantics.

### Cách sử dụng trong project

Nên tách hai feature set:

1. **PIT-explainable feature set:** chỉ dùng các raw field có semantics tương đối rõ và rolling features do project tự tạo.
2. **Extended Kaggle feature set:** bổ sung `C*`, `D*`, `M*`, `V*` để đối chiếu khả năng dự báo.

Lý do:

> Project không thể chứng minh Point-in-Time Correctness của một engineered feature nếu không biết feature đó được tính từ dữ liệu nào và ở thời điểm nào.

`V1`–`V339` có thể hữu ích cho model nhưng không nên là bằng chứng chính cho chất lượng Feature Store.

---

## 13. Identity table

Identity data chứa thông tin nhận dạng liên quan đến transaction, được thu thập bởi hệ thống fraud protection của Vesta và các đối tác digital security. Theo mô tả của competition host, nhóm này bao gồm:

- **Network connection information:** IP, ISP, proxy và các tín hiệu kết nối liên quan.
- **Digital signature:** user agent, browser, operating system, version và các tín hiệu thiết bị/phần mềm liên quan.

Tên trường và pairwise dictionary đã bị che giấu vì yêu cầu bảo vệ riêng tư và thỏa thuận hợp đồng. Chỉ một phần transaction có identity record.

### 13.1. `TransactionID`

Khóa nối với transaction table. Trong cả train và test identity, cột này không null và không duplicate.

### 13.2. `id_01`–`id_11`

Competition host xác nhận `id_01`–`id_11` là **numerical identity features**. Chúng được thu thập bởi Vesta và các security partners, có thể bao gồm các loại tín hiệu như:

- Device rating.
- IP-domain rating.
- Proxy rating.
- Behavioral fingerprint.
- Số lần đăng nhập hoặc đăng nhập thất bại.
- Thời gian account ở lại trên page.

Đây là các ví dụ về nhóm tín hiệu, không phải mapping cho từng cột. Ý nghĩa chi tiết bị che giấu bởi điều khoản với security partners.

```text
id_01, id_02, ..., id_11
```

Không nên suy luận riêng `id_01` là device rating hay `id_02` là proxy rating. Chỉ có thể khẳng định `id_01`–`id_11` là numerical identity features thuộc các nhóm tín hiệu nói trên.

### 13.3. `id_12`–`id_38`

Competition host xác nhận đây là các **categorical identity features**:

```text
id_12, id_13, ..., id_38
```

Một số cột có representation dạng số nhưng vẫn phải được xem là categorical code theo mô tả chính thức.

Nhiều cột identity có missing rate trên 90%, đặc biệt `id_07`, `id_08`, `id_21`–`id_27`.

### 13.4. `DeviceType`

Thông tin loại thiết bị ở mức khái quát. Đây là categorical feature chính thức. Train có hai giá trị chính và khoảng 2,37% missing trong identity table.

Có thể dùng để:

- Làm current-transaction feature.
- Theo dõi device type đã từng xuất hiện với entity hay chưa.
- Phân tích fraud rate theo device type.

### 13.5. `DeviceInfo`

Thông tin thiết bị/digital signature chi tiết hơn, có thể chứa tín hiệu liên quan tới user agent, browser, operating system hoặc version. Đây là categorical feature chính thức. Train có khoảng 1.786 giá trị khác nhau và 17,73% missing trong identity table. Không có mapping chính thức cho mọi chuỗi, nên chỉ diễn giải phần có thể đọc trực tiếp từ giá trị.

Đây là cột cardinality cao và chuỗi có thể không được chuẩn hóa. Trước khi sử dụng cần:

- Chuẩn hóa chữ hoa/thường.
- Tách family nếu có quy tắc chắc chắn.
- Giữ giá trị unknown riêng.
- Tránh one-hot toàn bộ giá trị thô.

---

## 14. Logic gán nhãn `isFraud`

Theo clarification của competition host, nhãn không chỉ mô tả việc chính transaction đó bị xác nhận gian lận ngay lập tức. Quy trình gán nhãn có thể tóm tắt như sau:

1. Một chargeback được báo cáo trên payment card thì transaction liên quan được gán `isFraud = 1`.
2. Các transaction xảy ra sau đó cũng có thể được gán fraud nếu có liên kết trực tiếp thông qua một trong các thuộc tính như:
   - User account.
   - Email address.
   - Billing address.
3. Nếu không có fraud/chargeback được báo cáo hoặc tìm thấy sau thời gian quan sát 120 ngày, transaction được gán `isFraud = 0`.

### 14.1. Ý nghĩa cần hiểu đúng

`isFraud = 1` có thể phản ánh cả:

- Transaction có chargeback được báo cáo.
- Transaction sau đó có liên hệ trực tiếp với account/email/billing address đã gắn với fraud.

Do đó đây không hoàn toàn là một nhãn chỉ dựa trên đặc điểm độc lập của từng transaction. Nó có thành phần **entity/link-based labeling**.

### 14.2. Negative label không tuyệt đối hoàn hảo

Một fraud thực tế có thể không được báo cáo vì cardholder không phát hiện, quên báo cáo hoặc đã quá claim period. Trong trường hợp đó, transaction gian lận có thể mang nhãn `0` mà dataset không thể nhận biết.

Vì vậy:

- `isFraud = 0` nên hiểu là “không có fraud được báo cáo/phát hiện theo logic và observation window”, không phải bằng chứng tuyệt đối rằng transaction chắc chắn hợp lệ.
- Dataset có khả năng chứa một lượng nhỏ false-negative label noise.

### 14.3. Ảnh hưởng tới project PIT Feature Store

- Không sử dụng label của transaction tương lai để tạo feature cho transaction quá khứ.
- Không tạo các feature như “số fraud trước đây của entity” nếu thời điểm chargeback/report không có trong dataset; nhãn có thể được xác định sau transaction.
- Phải chia train/validation/test theo `TransactionDT`, không random split làm đánh giá chính.
- Các aggregate dựa trên `isFraud` có rủi ro label leakage cao và bị loại khỏi PIT-explainable feature set.
- Khi diễn giải model, cần nhớ bài toán có yếu tố phát hiện entity/link liên quan tới fraud, không chỉ phân loại transaction độc lập.
- Observation window 120 ngày thuộc logic gán nhãn; nó khác với rolling feature window như 1 giờ, 24 giờ hoặc 7 ngày.

---

## 15. Schema khác nhau giữa train và test identity

Header thực tế đã tải có khác biệt:

```text
Train: id_01, id_02, ..., id_38
Test:  id-01, id-02, ..., id-38
```

Silver pipeline phải chuẩn hóa:

```text
id-01 → id_01
id-02 → id_02
...
id-38 → id_38
```

Không chuẩn hóa sẽ dẫn tới:

- Schema train/test không tương thích.
- Feature bị tạo thành hai cột khác nhau.
- Model không tìm thấy input khi inference.

Việc đổi tên phải được thực hiện có kiểm soát, chỉ áp dụng pattern `id-xx`, không thay mọi dấu `-` trong mọi tên cột một cách mù quáng.

---

## 16. Cột nào phù hợp cho từng mục tiêu?

| Mục tiêu | Cột ưu tiên | Lý do |
|---|---|---|
| Join transaction–identity | `TransactionID` | Khóa duy nhất được công bố. |
| Trục thời gian PIT | `TransactionDT` → `event_time` | Có thứ tự thời gian và dùng được cho window. |
| Target | `isFraud` | Nhãn binary của train. |
| Current transaction features | `TransactionAmt`, `ProductCD`, `card*`, `addr*`, email | Có sẵn tại observation time theo giả định của project. |
| Candidate entity | `card1` kết hợp một số `card*`, `addr1` | Có giao dịch lặp nhưng cần đánh giá riêng. |
| Rolling amount features | `TransactionAmt` | Semantics rõ và có thể aggregate. |
| Rolling diversity | `ProductCD`, email, device | Có thể đếm distinct trong lịch sử. |
| Optional model features | `C*`, `D*`, `M*`, `V*`, `id_*` | Có thể có predictive value nhưng semantics/leakage khó chứng minh. |

---

## 17. Phân loại theo rủi ro Point-in-Time

| Nhóm cột | PIT status ban đầu | Cách sử dụng |
|---|---|---|
| `TransactionID` | Không phải feature dự báo | Chỉ dùng làm key/tracing. |
| `TransactionDT` | Được phép làm cutoff | Chuyển thành `event_time`. |
| `TransactionAmt`, `ProductCD`, card/address/email hiện tại | Có thể dùng nếu giả định đã biết tại scoring time | Ghi rõ assumption trong data contract. |
| Rolling features tự tạo | Có thể chứng minh PIT | Chỉ dùng events có `history_time < prediction_time`. |
| Identity/device | Có điều kiện | Chỉ dùng nếu identity đã tồn tại tại transaction time; dataset không có ingestion time để kiểm chứng hoàn toàn. |
| `C*`, `D*`, `M*`, `V*` | Chưa xác minh | Tách khỏi PIT-explainable baseline. |
| `isFraud` | Cấm làm input | Chỉ dùng làm label/evaluation; không aggregate label vì thời điểm chargeback/report không có trong dataset. |

---

## 18. Những điều không nên suy diễn

- Không gọi `TransactionID` là customer/account ID.
- Không khẳng định `card1` là số thẻ hoặc BIN cụ thể.
- Không khẳng định `dist1/dist2` là khoảng cách địa lý.
- Không đặt tên nghiệp vụ cụ thể cho `C*`, `D*`, `M*`, `V*`, `id_*`.
- Không coi synthetic epoch là ngày thật.
- Không coi missing identity là lỗi dữ liệu; nó là đặc điểm của dataset.
- Không mặc định mọi feature Kaggle đều point-in-time correct.
- Không hiểu `isFraud = 0` là bảo đảm tuyệt đối transaction hợp lệ.
- Không hiểu mọi `isFraud = 1` là chargeback độc lập của chính transaction đó; label có thể được lan truyền qua liên kết entity theo logic của host.

---

## 19. Các tài liệu liên quan trong project

- [`dataset_audit_summary.md`](../reports/dataset_audit_summary.md): kết quả profiling thực tế.
- [`data_contract.md`](./data_contract.md): các invariant mà pipeline phải kiểm tra.
- [`PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md`](../PROJECT_OUTLINE_IEEE_CIS_PIT_FEATURE_STORE.md): kế hoạch triển khai.
- [`LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md`](../LY_THUYET_POINT_IN_TIME_CORRECT_FEATURE_STORE.md): lý thuyết PIT Feature Store.

## 20. Nguồn

- Kaggle, **IEEE-CIS Fraud Detection — Dataset Description**: <https://www.kaggle.com/competitions/ieee-fraud-detection/data>
- Kaggle host discussion, **Data Description (Details and Discussion)**: <https://www.kaggle.com/c/ieee-fraud-detection/discussion/101203>
- Kaggle host clarification, **Identity/DeviceInfo discussion**: <https://www.kaggle.com/c/ieee-fraud-detection/discussion/101203#583227>
- Kaggle host clarification, **Labeling logic**: <https://www.kaggle.com/c/ieee-fraud-detection/discussion/101203#588953>
- Liu et al., **Optimizing Data Pipelines for Machine Learning in Feature Stores**, PVLDB 2023: <https://www.vldb.org/pvldb/vol16/p4230-camacho-rodriguez.pdf>
