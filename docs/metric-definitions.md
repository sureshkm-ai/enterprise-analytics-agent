# Governed metric definitions

These assumptions were recorded before implementing the milestone 1 calculation. They are explicit product choices for synthetic retail data, not claims about a particular company's accounting policy.

## net_revenue, definition 1.0.0

- **Calculation:** sum `quantity * unit_price_cents - discount_cents - approved_refund_cents` at the order-item grain, then group by the requested allowed order dimensions. Convert the final integer cents to exact decimal USD.
- **Eligible order statuses:** `completed` and `shipped`. `pending` and `canceled` orders contribute neither sales nor refunds. Payment status does not independently determine eligibility; a completed order is the authoritative business event in this fixture.
- **Discounts:** `discount_cents` is the total discount for the entire line, not a per-unit amount. It is subtracted once. Synthetic data has no separate order-level discount.
- **Tax and shipping:** excluded from both sales and refund amounts used by this metric. They remain on orders for reconciliation. Payments can include both, and do not define merchandise revenue.
- **Currency and units:** USD only, integer cents at rest and decimal dollars in responses. No currency conversion. Other-currency orders are excluded explicitly.
- **Refund approval:** only `approved` refunds count. `pending` and `rejected` refunds do not. Refunds identify an order item and are merchandise amounts after discount, excluding tax and shipping. Partial refunds and multiple independent approved refunds for one item are additive.
- **Refund time attribution:** refunds reduce the original order date's revenue regardless of their event/approval date. This is a restatable snapshot metric, with no as-of cutoff. A refund approved after the query's end still reduces the original-period result if present in the loaded snapshot. `approved_at` is lineage, not a query filter.
- **Time semantics:** `orders.ordered_at` is a UTC business date. Start is inclusive, end is exclusive: `start <= ordered_at < end`. There is no session timezone, implicit today, or rolling-window default.
- **Aggregation grain:** first aggregate approved refunds by `(tenant_id, order_item_id)`, then calculate once per `(tenant_id, order_item_id)`, then sum by allowed dimensions. Do not join payment events into this calculation.
- **Dimensions and filters:** `region` and `channel`, taken from the order at purchase time. Filters are equality against one or more values, AND across dimensions and OR within each dimension. Arbitrary SQL, expressions, dimensions, and request-level business-status overrides are rejected.
- **Relationships:** customers have many orders, orders have many order items and payments, products have many order items, and order items have many refunds. Every relationship includes `tenant_id`.
- **Duplicate events:** all six sources have a business key scoped by tenant. Identical repeats of the same business record collapse. Different records sharing that key are rejected; no ambiguous latest-write-wins rule. Distinct refund IDs remain separate refunds even if their amounts match.
- **Empty results:** grouped queries return `rows: []`; ungrouped queries return one row with `value: "0.00"`. An eligible zero-revenue group remains present.
- **Negative revenue:** supported for externally supplied trusted snapshots (e.g. adjustments). The generator does not intentionally over-refund. This milestone does not enforce a complete accounting ledger or reconciliation policy.

## Independent worked example

Within the date range, an eligible North order has two lines: `2 * $10.00 - $3.00 = $17.00`, and `1 * $8.00 - $0.00 = $8.00`. The first line has approved refunds of $4.00 and $1.50, and a pending refund of $9.00. North net revenue is therefore `$17.00 + $8.00 - $4.00 - $1.50 = $19.50`. Exact repeats of a line or refund do not change this result. A canceled order's $100.00 sale and approved refund do not contribute. Tax, shipping, and payment events do not change $19.50.

Tests use small manually authored fixtures and literal expected results based on arithmetic like this. Expected results must never be derived from the adapter's query or the synthetic generator.

## Public metadata and internal execution

The model-visible metric description uses business terms: calculation prose, the logical `order_item` grain, the `order_date` time dimension, allowed dimensions, relationship descriptions, and fixed business filters. It does not return the executable expression, source-table/column mappings, or tenant-scoped join keys. Those remain in the internal governed catalog and are translated by adapters. Dimension discovery returns semantic names, descriptions, and authorized values only.

The pre-commit milestone 1 review corrected the original description schemas. The committed v1 models at `64cbea4` are the compatibility baseline, preserved by milestone 2. Query request/response schemas and net revenue definition 1.0.0 calculation semantics remain unchanged. Incompatible published changes require a new API version; milestone 2 adds v2 rather than widening v1 monetary results.

## Milestone 2 definitions — recorded before implementation

The existing `net_revenue` definition 1.0.0 above is unchanged. Every metric uses the same completed/shipped, USD, trusted tenant/region, purchase-time dimension, and `[start, end)` order-date rules. An eligible order must have at least one valid item. All present snapshot data is validated; malformed items are rejected rather than silently skipped.

| Metric | Governed calculation | Logical grain | Unit / final precision |
| --- | --- | --- | --- |
| `gross_sales` | Sum eligible item quantity × unit price, before discounts/refunds; exclude tax/shipping. | order item | USD currency / 2 decimal places |
| `net_revenue` | Preserve the existing discounted merchandise sales less approved merchandise refunds exactly. | order item | USD currency / 2 decimal places |
| `order_count` | Count distinct eligible orders having at least one valid item. | order | count / integer |
| `average_order_value` | Aggregate net revenue divided by aggregate eligible order count. | order | USD currency / 2 decimal places |
| `return_rate` | Distinct eligible orders with at least one received physical item return divided by aggregate eligible order count. | order | ratio / 6 decimal places, fraction in [0, 1] |

Refunds and physical returns are separate facts: an approved refund does not imply a physical return, and a received physical return need not have a refund. Only return status `received` contributes; `pending` and `rejected` do not. A partial physical return counts its order once, and multiple return events/items for that order still count once. Exact event replays collapse by `(tenant_id, return_id)`; contradictory records sharing that key fail validation.

Physical return events reference tenant-scoped items, use positive integer quantities no greater than their purchased item quantity, and contain an event date plus an optional received date (required for `received`). Event and received dates are lineage, not query filters. Refunds and returns are attributed to the original order period using the loaded snapshot, with **no as-of cutoff**. Later events can restate earlier periods. This milestone does not implement a complete physical inventory ledger or cumulative return reconciliation.

For each requested output group, aggregate exact numerators and denominators first. Never average subgroup ratios. Compute division using exact arithmetic and apply `ROUND_HALF_UP` only to the final value: 2 places for average order value and 6 for return rate. A zero denominator returns JSON `null`, including an ungrouped empty snapshot/query. Non-ratio sums/counts return zero for an ungrouped empty result. All grouped queries with no eligible items return `rows: []`.

Currency and ratio values serialize as exact decimal strings; counts are JSON integers. Nonmonetary results have `currency: null` in v2; monetary results use `currency: "USD"`. The ratios' constituent counts/sums are not exposed as arbitrary model-defined calculations. The catalog governs each supported expression, precision, status rule, dimension, and relationship; SQL remains inside the adapter.

The six original table schemas remain required by the reference snapshot adapter. `returns.parquet` is optional for all metrics except `return_rate`; querying that metric without the file raises a clear missing-data error. An existing but empty, correctly typed returns table means no received returns and yields zero when eligible orders exist. Return generation uses a separate deterministic random stream and does not consume or alter the original sales/refund generator's random sequence.

### Versioning and migration

V1 requests/responses and net revenue calculation stay unchanged. V1 discovery continues to advertise only net revenue. New versioned v2 request/response models support all five metrics and currency/count/nullable-ratio results; v2 descriptions advertise the appropriate logical grain and final precision. V2 uses `api_version: "v2"` throughout its envelope and nested contract objects. Callers opt into the v2 models; trusted authorization context is still passed separately. The CLI retains its default v1 net revenue result and selects v2 for other metrics, with an explicit API-version option for migration. V1 requests for new metrics receive a clear version error.

### Independent multi-metric example

Use three eligible orders, including two in North and one in South. North order A has `2 × $10 - $3` and `1 × $8` lines plus approved refunds $4 and $1.50: gross $28, net $19.50. North order B has a $10 line with no refund: gross/net $10. South order C has `3 × $5 - $2`: gross $15, net $13. Aggregate gross is **$53**, net **$42.50**, order count **3**, and average order value **$14.17** (not the average of regional averages). If only order A has a received physical return, total return rate is **0.333333**; North is **0.500000**, South **0.000000**. Duplicate events and additional returned items on A do not change the numerator. Tests may use this or smaller hand-authored examples with independently calculated literal answers.

## Milestone 3 parity fixture — unchanged metric definitions

Athena must preserve the five definitions above; there is no new accounting policy. Its Parquet inventory is validated before publication, exact replays are canonicalized, and malformed tenant-scoped relationships or conflicting events fail readiness. Snapshot versions isolate both data locations and Glue table names. Missing returns still raises an error for return rate, while an empty typed source means zero returned orders.

The new independent AWS fixture adds an approved $1 refund to North order B (with no physical return), and a received physical return to South order C (with no refund). Order A retains multiple approved refunds, partial/multiple physical returns, and exact event replays. Literal expected totals are **gross $53.00, net $41.50, count 3, AOV $13.83, return rate 0.666667**. North is gross $38.00/net $28.50/count 2/AOV $14.25/rate 0.500000; South is gross $15.00/net $13.00/count 1/AOV $13.00/rate 1.000000. Additional canceled/pending/non-USD, boundary-date, hidden-region, and second-tenant records test eligibility and authorization.

Both Athena and DuckDB must independently match these literals, including grouped/ungrouped queries, zero denominators, snapshots with absent/empty returns, refunds versus returns, duplicate events, and original-order date boundaries. Adapter agreement alone is not acceptance. Athena uses DECIMAL(38,0) integer aggregates instead of DuckDB HUGEINT, then performs final exact rational rounding in application code. The user reports the user-executed live parity gate passed with **66 passed, 458 deselected in 111.94s**; it was not rerun during this documentation update. Development live validation has passed, with the remaining hosted-CI confirmation and PR review/merge status recorded in [progress](progress.md). These results leave the public contracts and business rules unchanged.
