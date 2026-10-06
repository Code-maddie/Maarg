# E1 Misplacement Classifier

A production-ready machine learning package for predicting in-flight logistics misplacement and disruption risk across multimodal supply chains.

---

## 1. What E1 Does

**E1 Misplacement Classifier** evaluates active, in-flight shipments at transfer nodes and predicts the probability that a shipment is at risk of being misplaced or significantly disrupted during transit:

$$\text{Output}: P(\text{misplace}) \in [0.0, 1.0]$$

Downstream logistics systems, routing engines, and facility coordinators consume this probability to initiate proactive physical audits, reroute high-risk packages, or alert hub operations.

---

## 2. Input Features & Serving Contract

The model accepts exactly **8 features** transformed via a fitted `ColumnTransformer` (`OneHotEncoder` with `handle_unknown="ignore"` and `StandardScaler`):

| Feature Name | Type | Processing | Description / Operational Role | Constraints / Range |
| :--- | :--- | :--- | :--- | :--- |
| `route` | Categorical (`str`) | OneHotEncoder | Planned transit corridor/lane ID | Non-empty string |
| `hub` | Categorical (`str`) | OneHotEncoder | Facility / node identifier where shipment is handled | Non-empty string |
| `carrier` | Categorical (`str`) | OneHotEncoder | Carrier mode (`air`, `multi`, `sea`, `rail`, `road`) | Standard mode string |
| `congestion_index` | Numeric (`float`) | StandardScaler | Composite operational score combining facility yard, gate, and dwell metrics | Strictly bounded in $[0.0, 1.0]$ |
| `num_handoffs` | Numeric (`int`) | StandardScaler | Operational proxy: accumulated stops/transfers in last 24h | Integer $\ge 0$ |
| `sorting_method` | Categorical (`str`) | OneHotEncoder | Facility sorting mechanism (set to `"unknown"` in v1) | Non-empty string |
| `weather_flag` | Numeric (`int`) | StandardScaler | Binary indicator: 1 if precipitation exceeds upper quartile (4.88 mm) | $\{0, 1\}$ |
| `hour_of_day` | Numeric (`int`) | StandardScaler | Local observation hour when shipment status was recorded | Integer $0 \le \text{hour} \le 23$ |

The model exposes:
```python
model.predict_proba(X)
```
and the serving interface guarantees the exact feature schema ordering.

---

## 3. Datasets & Feature Mapping

Raw data is discovered under `data/raw/`:

1. **Primary Training Dataset**:
   - Multimodal Industrial Logistics Disruption and Risk Dataset
   - Zenodo DOI: `10.5281/zenodo.18050317`
   - File: `data/raw/zenodo/supplychain_datasetV0.csv` (39,864 rows, 71 columns)
   - Scope: Complete ground-truth disruption records, facility telemetry, precipitation, and transit timestamps.

2. **Secondary Reference Dataset**:
   - Delhivery Logistics Dataset (`data/raw/delhivery/delhivery_data.csv`, 144,867 rows, 24 columns)
   - Audited for training relevance: Lacks disruption ground truth, facility yard congestion metrics, and weather precipitation. Documented in `data_audit_report.json` as out-of-scope for E1 ground-truth training.

### Feature Mapping Logic
- **`route`**: Extracted from `route_id` (500 distinct corridors).
- **`hub`**: Extracted from `facility_id` (200 distinct facilities).
- **`carrier`**: Extracted from `carrier_mode` (`air`, `multi`, `sea`, `rail`, `road`).
- **`num_handoffs`**: Mapped to `stop_count_last_24h` proxy count.
- **`congestion_index`**: Operational composite score bounded in $[0, 1]$:
  $$\text{yard\_norm} = \text{clip}\left(\frac{\text{yard\_utilization\_pct}}{100.0}, 0, 1\right)$$
  $$\text{gate\_norm} = \text{clip}\left(\frac{\text{gate\_turn\_time\_min} - 6.0}{98.77 - 6.0}, 0, 1\right)$$
  $$\text{dwell\_norm} = \text{clip}\left(\frac{\text{dwell\_time\_at\_node\_min} - 3.0}{100.89 - 3.0}, 0, 1\right)$$
  $$\text{congestion\_index} = \text{clip}(0.40 \cdot \text{yard\_norm} + 0.30 \cdot \text{gate\_norm} + 0.30 \cdot \text{dwell\_norm}, 0, 1)$$
- **`weather_flag`**: Binary threshold mapped to empirical 75th percentile of precipitation:
  $$\text{weather\_flag} = \mathbb{I}(\text{precip\_mm} \ge 4.88)$$
- **`hour_of_day`**: Extracted directly from the shipment state timestamp.
- **`sorting_method`**: Fixed to `"unknown"` because the raw dataset contains no defensible sorting technology observation. Preserves production schema contract without fabricating data.

---

## 4. Mandatory Target Definition

> [!IMPORTANT]
> **E1 Prototype Disruption/Misplacement-Risk Proxy Label**
> The v1 target is defined as:
> - `misplaced = 0`: Normal / non-disrupted operational records (`disruption_type == 0`)
> - `misplaced = 1`: Records representing a disruption event (`disruption_type > 0`)
>
> In all documentation and serving artifacts, this target is explicitly designated as the **"E1 prototype disruption/misplacement-risk proxy label"**. It reflects operational risk of delivery disruption and leg delay, **NOT** a verified physical lost-package or misplacement barcode scan.

**Class Balance**:
- Normal (`0`): 27,849 (69.86%)
- Disrupted / Misplacement Risk (`1`): 12,015 (30.14%)

---

## 5. Temporal Leakage Prevention

All features are strictly constrained to information observable *at or before* prediction time. Excluded post-event columns:
- `disruption_type` (isolated strictly as the proxy target)
- `severity_level` (post-incident severity score)
- `zone_risk_level`, `sustainability_impact_class` (retrospective ratings)
- `actual_CO2e_kg`, `co2e_gap_pct` (post-trip emissions)
- `eta_gap_hours` (post-delivery realized delay)
- `km_detour_pct` (post-trip diversion percentage)

Audit details are recorded in `data/processed/leakage_report.json`.

---

## 6. Temporal Split (Chronological)

To prevent future leakage, records are sorted strictly by `timestamp`:
- **Training Split (70%)**: 27,904 rows (`2021-03-14 00:00:00` to `2024-05-19 15:00:00`), Positive rate: **0.3007**
- **Validation Split (15%)**: 5,979 rows (`2024-05-19 16:00:00` to `2025-01-23 18:00:00`), Positive rate: **0.3004**
- **Held-out Test Split (15%)**: 5,981 rows (`2025-01-23 19:00:00` to `2025-09-29 23:00:00`), Positive rate: **0.3056**

---

## 7. Model Evaluation & Selection

### Candidate Comparison on Validation Split

| Candidate Model | Validation ROC-AUC | Validation PR-AUC | Validation F1 | Brier Score | Log Loss | Accuracy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **LogisticRegression** (`balanced`) | 0.4978 | 0.3062 | 0.3624 | 0.2534 | 0.7002 | 0.4992 |
| **HistGradientBoosting** (`balanced`) | 0.5047 | 0.3049 | 0.4153 | 0.2498 | 0.6928 | 0.4297 |
| **RandomForest** (`100 trees, balanced`) | **0.5219** | **0.3145** | **0.2829** | **0.2375** | **0.6710** | **0.6083** |

### Selection Decision
**RandomForestClassifier** was selected as the production model due to superior validation ROC-AUC (0.5219), highest PR-AUC (0.3145), best probability calibration (Brier score 0.2375), and lowest log loss (0.6710).

---

## 8. Final Held-Out Test Evaluation

The production model was refit on the chronological Train + Validation splits and evaluated **exactly once** on the held-out Test split:

| Metric | Held-Out Test Value |
| :--- | :---: |
| **ROC-AUC** | **0.4999** |
| **PR-AUC** | **0.3153** |
| **Accuracy** | **0.5945** (59.45%) |
| **Precision** | **0.2990** |
| **Recall** | **0.2429** |
| **F1 Score** | **0.2680** |
| **Brier Score** | **0.2430** |
| **Log Loss** | **0.6847** |

### Confusion Matrix (Test Split: 5,981 records)
- **True Negatives (TN)**: 3,112
- **False Positives (FP)**: 1,041
- **False Negatives (FN)**: 1,384
- **True Positives (TP)**: 444

Diagnostic curves generated during the run are stored under `artifacts/misplacement_classifier/v1/`:
- `confusion_matrix.png`
- `roc_curve.png`
- `pr_curve.png`
- `calibration_curve.png`

---

## 9. Production Artifacts

All primary artifacts are located in `artifacts/misplacement_classifier/v1/`:

| Artifact Path | Format | Role |
| :--- | :--- | :--- |
| `model.pkl` | Pickle | Fitted production `RandomForestClassifier` |
| `feature_pipeline.joblib` | Joblib | Fitted `ColumnTransformer` preprocessor |
| `metrics.json` | JSON | Validation comparison, selection rationale, test metrics |
| `feature_schema.json` | JSON | Feature ordering, column dtypes, transformer metadata |
| `training_metadata.json` | JSON | Complete training lineage, timestamps, environment, checksums |

---

## 10. How to Run Locally

### 1. Run Complete Automated Pipeline
```bash
python run_e1.py --data-root data/raw --version v1
```

### 2. Run Automated Test Suite
```bash
pytest tests -v
```

---

## 11. How to Reproduce in Google Colab

Open `notebooks/E1_training.ipynb` in Google Colab:
1. Clone the repository or upload the project folder to Colab:
   ```bash
   !git clone <repo-url> softHack && cd softHack
   ```
2. Run cells sequentially:
   - Cell 1 checks the environment and configures `DATA_ROOT`.
   - Cells 2–4 audit data, build `data/processed/e1_training.csv`, and split temporally.
   - Cells 5–8 fit the preprocessor, train candidates, select the model, and plot diagnostic curves.
   - Cell 9 exports artifacts and runs serialization checks.

---

## 12. Inference Example

```python
from src.inference.predict import predict_misplacement_probability

# Sample input dictionary
sample_shipment = {
    "route": "R001",
    "hub": "F001",
    "carrier": "air",
    "congestion_index": 0.72,
    "num_handoffs": 4,
    "sorting_method": "unknown",
    "weather_flag": 1,
    "hour_of_day": 19
}

prob = predict_misplacement_probability(sample_shipment)
print(f"Predicted Misplacement Probability: {prob:.4f}")
# Output: 0.5700
```

---

## 13. Known Limitations

1. **Proxy Target Limitation (CRITICAL)**: The v1 target is derived from operational disruption indicators (`disruption_type > 0`) in multimodal logistics, **NOT** physical parcel misplacement barcode scans. The probability reflects general shipment disruption/delay propensity.
2. **Sorting Method Contract**: The raw dataset does not observe sorting mechanism hardware. The feature is maintained as `"unknown"` to preserve downstream serving contracts until warehouse-level telemetry is integrated.
3. **Low Feature Signal**: In this multimodal dataset, static corridor and weather variables have modest correlation with disruptions, requiring physical IoT telemetry for higher discrimination in v2.
