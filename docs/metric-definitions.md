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

This corrects the unreleased milestone's v1 description schemas before their first commit; query request/response schemas and definition 1.0.0 calculation semantics are unchanged. Once published, incompatible contract changes require a new API version.
