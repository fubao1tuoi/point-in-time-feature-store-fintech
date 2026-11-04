# IEEE-CIS Dataset Audit Summary

> Sinh tự động lúc `2026-11-02T07:50:41.493792+00:00` bởi `profile-ieee-cis`.

## 1. Dataset inventory

| Source | Rows | Columns | Size (MB) | Runtime (s) |
|---|---:|---:|---:|---:|
| `train_transaction` | 590,540 | 394 | 651.69 | 101.04 |
| `train_identity` | 144,233 | 41 | 25.30 | 3.67 |
| `test_transaction` | 506,691 | 393 | 584.79 | 83.44 |
| `test_identity` | 141,907 | 41 | 24.60 | 3.58 |

## 2. Data integrity checks

### `train_transaction`

- Null `TransactionID`: 0
- Unique `TransactionID`: 590,540
- Duplicate `TransactionID`: 0
- `TransactionDT` monotonic: True
- Negative `TransactionDT`: 0
- Negative `TransactionAmt`: 0

### `train_identity`

- Null `TransactionID`: 0
- Unique `TransactionID`: 144,233
- Duplicate `TransactionID`: 0
- `TransactionDT` monotonic: None
- Negative `TransactionDT`: —
- Negative `TransactionAmt`: —

### `test_transaction`

- Null `TransactionID`: 0
- Unique `TransactionID`: 506,691
- Duplicate `TransactionID`: 0
- `TransactionDT` monotonic: True
- Negative `TransactionDT`: 0
- Negative `TransactionAmt`: 0

### `test_identity`

- Null `TransactionID`: 0
- Unique `TransactionID`: 141,907
- Duplicate `TransactionID`: 0
- `TransactionDT` monotonic: None
- Negative `TransactionDT`: —
- Negative `TransactionAmt`: —

## 3. Target and temporal profile

- Fraud: 20,663 (3.4990%)
- Non-fraud: 569,877
- `TransactionDT` range: `86400` → `15811131`
- Relative days represented: 182
- `TransactionAmt` range: `0.251` → `31937.391`

## 4. Identity coverage

- **Train**: 144,233/590,540 rows (24.4239%).
- **Test**: 141,907/506,691 rows (28.0066%).

## 5. Train/test schema comparison

### `transaction`

- Compatible after expected target removal: **True**.
- Train-only columns: `isFraud`.
- Test-only columns: none.

### `identity`

- Compatible after expected target removal: **False**.
- Train-only columns: `id_01`, `id_02`, `id_03`, `id_04`, `id_05`, `id_06`, `id_07`, `id_08`, `id_09`, `id_10`, `id_11`, `id_12`, `id_13`, `id_14`, `id_15`, `id_16`, `id_17`, `id_18`, `id_19`, `id_20`, `id_21`, `id_22`, `id_23`, `id_24`, `id_25`, `id_26`, `id_27`, `id_28`, `id_29`, `id_30`, `id_31`, `id_32`, `id_33`, `id_34`, `id_35`, `id_36`, `id_37`, `id_38`.
- Test-only columns: `id-01`, `id-02`, `id-03`, `id-04`, `id-05`, `id-06`, `id-07`, `id-08`, `id-09`, `id-10`, `id-11`, `id-12`, `id-13`, `id-14`, `id-15`, `id-16`, `id-17`, `id-18`, `id-19`, `id-20`, `id-21`, `id-22`, `id-23`, `id-24`, `id-25`, `id-26`, `id-27`, `id-28`, `id-29`, `id-30`, `id-31`, `id-32`, `id-33`, `id-34`, `id-35`, `id-36`, `id-37`, `id-38`.

## 6. Missing-data highlights

### `train_transaction`

- Columns with at least 90% missing values: **2**.
- Highest missing columns: `dist2` (93.63%), `D7` (93.41%).

### `train_identity`

- Columns with at least 90% missing values: **9**.
- Highest missing columns: `id_24` (96.71%), `id_25` (96.44%), `id_07` (96.43%), `id_08` (96.43%), `id_21` (96.42%), `id_26` (96.42%), `id_22` (96.42%), `id_23` (96.42%), `id_27` (96.42%).

### `test_transaction`

- Columns with at least 90% missing values: **1**.
- Highest missing columns: `dist2` (92.81%).

### `test_identity`

- Columns with at least 90% missing values: **9**.
- Highest missing columns: `id-24` (96.66%), `id-25` (96.45%), `id-26` (96.44%), `id-07` (96.44%), `id-08` (96.44%), `id-21` (96.44%), `id-22` (96.43%), `id-23` (96.43%), `id-27` (96.43%).

## 7. Selected cardinalities

| Source | Column | Cardinality | Null % |
|---|---|---:|---:|
| `train_transaction` | `P_emaildomain` | 59 | 15.9949% |
| `train_transaction` | `ProductCD` | 5 | 0.0000% |
| `train_transaction` | `R_emaildomain` | 60 | 76.7516% |
| `train_transaction` | `TransactionID` | 590,540 | 0.0000% |
| `train_transaction` | `addr1` | 332 | 11.1264% |
| `train_transaction` | `addr2` | 74 | 11.1264% |
| `train_transaction` | `card1` | 13,553 | 0.0000% |
| `train_transaction` | `card2` | 500 | 1.5127% |
| `train_transaction` | `card3` | 114 | 0.2650% |
| `train_transaction` | `card4` | 4 | 0.2670% |
| `train_transaction` | `card5` | 119 | 0.7212% |
| `train_transaction` | `card6` | 4 | 0.2660% |
| `train_transaction` | `isFraud` | 2 | 0.0000% |
| `train_identity` | `DeviceInfo` | 1,786 | 17.7262% |
| `train_identity` | `DeviceType` | 2 | 2.3732% |
| `train_identity` | `TransactionID` | 144,233 | 0.0000% |
| `test_transaction` | `P_emaildomain` | 60 | 13.6557% |
| `test_transaction` | `ProductCD` | 5 | 0.0000% |
| `test_transaction` | `R_emaildomain` | 60 | 73.1848% |
| `test_transaction` | `TransactionID` | 506,691 | 0.0000% |
| `test_transaction` | `addr1` | 292 | 12.9485% |
| `test_transaction` | `addr2` | 72 | 12.9485% |
| `test_transaction` | `card1` | 13,244 | 0.0000% |
| `test_transaction` | `card2` | 497 | 1.7079% |
| `test_transaction` | `card3` | 115 | 0.5925% |
| `test_transaction` | `card4` | 4 | 0.6090% |
| `test_transaction` | `card5` | 102 | 0.8974% |
| `test_transaction` | `card6` | 3 | 0.5935% |
| `test_identity` | `DeviceInfo` | 2,226 | 18.9208% |
| `test_identity` | `DeviceType` | 2 | 3.5065% |
| `test_identity` | `TransactionID` | 141,907 | 0.0000% |

## 8. Initial findings for the PIT Feature Store

- `TransactionDT` is a relative time offset, not a real timestamp. The project must use a documented synthetic epoch.
- Identity data exists for only part of the transactions, so transaction-to-identity enrichment must use a left join.
- The dataset has no official customer identifier. A surrogate entity key must be evaluated separately before rolling features are finalized.
- The target is imbalanced; chronological evaluation and PR-AUC are required in addition to ROC-AUC.
- Columns with opaque semantics should not be the only evidence of point-in-time correctness.

## 9. Generated artifacts

- Full machine-readable profile: `reports/generated/dataset_profile.json`.
- This summary: `reports/dataset_audit_summary.md`.
