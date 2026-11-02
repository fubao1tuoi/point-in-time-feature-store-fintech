# Data contract

Data contract chính thức sẽ được sinh sau bước dataset profiling.

Các invariant ban đầu:

- `TransactionID` không null và duy nhất trong transaction source.
- `TransactionDT` không null và không âm.
- `TransactionAmt` là numeric và không âm.
- `isFraud` thuộc `{0, 1}` trong training data.
- Identity là dữ liệu tùy chọn và phải được nối bằng left join.

