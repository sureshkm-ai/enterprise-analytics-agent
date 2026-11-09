# Independent retail oracle evidence

Schema: `retail-oracle-notes-v1`. The input files are exact version-pinned canonical
publication downloads, verified again by byte hash, size, physical schema, row inventory,
required fields, tenant-scoped relationships and duplicate/conflict rules.
These results are independent expected values, not agent/adapter outputs or live results.
No model invocation, Athena query, source regeneration or publication was used.

Manifest SHA-256: `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797`; seed `20260101`; tenant `retail_demo`;
authorized regions North/South; reference date `2025-04-01`.

## Method and review

`oracle.py` decodes Parquet rows without metric SQL, imports only public contracts and
operator case models, and builds its own dictionaries and integer-cent ledger.
Exact duplicates collapse; conflicting business keys and invalid relationships fail.
Completed/shipped USD orders with items are counted once. Gross minus line discounts
minus approved USD item refunds gives net; tax, shipping and payments are excluded.
Received physical returns flag distinct orders independently of refunds. Event dates
never filter original order-date contributions; the snapshot has no as-of cutoff.
Use aggregate net cents/(100 × aggregate order count) for AOV and returned-order
count/order count for return rate, final HALF_UP at 2/6 places in a local precision-120
Decimal context. Zero denominator is null; empty grouped output has no rows.

Handwritten fixture proofs establish $53.00 gross, $41.50 net, 3 orders, $13.83 AOV
and 0.666667 returns. AOV tie $0.005 rounds to $0.01; 1/128=.0078125 rounds
to .007813. The tests do not obtain expected values from this utility or production code.
`contributions.csv` retains every canonical item, including excluded scopes/statuses;
`eligible` reflects business status/currency only. Apply tenant/region/date/filter scope
before summing. Multiple item rows must be deduplicated by order ID for both counts.

The cohort worksheet below records every operand. Currency sums divide cents by 100;
for each ratio divide these aggregate numerators/denominators before final rounding.
Literal goldens remain frozen during evaluation; reviewed changes require a new freeze.
The independent root agent reviewed the selected operand arithmetic and cohort
scope below before live execution. This records an agent review, with no claim of
human review or live validation; `oracle-provenance.json` records its scope.

## Cohort contribution worksheet

| Case/query | Metric and group | Gross cents | Discount cents | Approved refund cents | Net cents | Distinct orders | Distinct received-return orders |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q01/1 | gross_sales {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q01/1 | gross_sales {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q02/1 | net_revenue {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q02/1 | net_revenue {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q03/1 | order_count {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q03/1 | order_count {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q04/1 | average_order_value {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q04/1 | average_order_value {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q05/1 | return_rate {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q05/1 | return_rate {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q06/1 | gross_sales {} | 188400 | 10755 | 10942 | 166703 | 27 | 4 |
| Q07/1 | net_revenue {} | 188400 | 10755 | 10942 | 166703 | 27 | 4 |
| Q08/1 | order_count {} | 188400 | 10755 | 10942 | 166703 | 27 | 4 |
| Q09/1 | average_order_value {} | 188400 | 10755 | 10942 | 166703 | 27 | 4 |
| Q10/1 | return_rate {} | 188400 | 10755 | 10942 | 166703 | 27 | 4 |
| Q11/1 | net_revenue {"channel": "online"} | 29975 | 1323 | 3211 | 25441 | 4 | 1 |
| Q11/1 | net_revenue {"channel": "store"} | 28300 | 1661 | 331 | 26308 | 6 | 0 |
| Q12/1 | order_count {"channel": "online", "region": "North"} | 9400 | 765 | 1093 | 7542 | 3 | 1 |
| Q12/1 | order_count {"channel": "store", "region": "North"} | 10150 | 475 | 0 | 9675 | 2 | 0 |
| Q12/1 | order_count {"channel": "online", "region": "South"} | 13225 | 985 | 445 | 11795 | 1 | 0 |
| Q12/1 | order_count {"channel": "store", "region": "South"} | 22750 | 1596 | 1605 | 19549 | 2 | 1 |
| Q13/1 | net_revenue {} | 30650 | 1680 | 1746 | 27224 | 4 | 1 |
| Q14/1 | net_revenue {} | 55525 | 3821 | 3143 | 48561 | 8 | 2 |
| Q15/1 | net_revenue {} | 0 | 0 | 0 | 0 | 0 | 0 |
| Q16/1 | net_revenue {} | 0 | 0 | 0 | 0 | 0 | 0 |
| Q17/1 | average_order_value {} | 58275 | 2984 | 3542 | 51749 | 10 | 1 |
| Q18/1 | net_revenue {} | 12625 | 388 | 1212 | 11025 | 1 | 1 |
| Q19/1 | net_revenue {} | 0 | 0 | 0 | 0 | 0 | 0 |
| Q20/1 | return_rate {} | 0 | 0 | 0 | 0 | 0 | 0 |
| Q21/1 | order_count: no groups | — | — | — | — | 0 | 0 |
| Q22/1 | net_revenue {} | 1000 | 0 | 250 | 750 | 1 | 0 |
| Q23/1 | return_rate {} | 1500 | 75 | 0 | 1425 | 1 | 1 |
| Q24/1 | gross_sales {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q24/1 | gross_sales {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q24/2 | net_revenue {"region": "North"} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| Q24/2 | net_revenue {"region": "South"} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |
| Q25/1 | average_order_value {} | 55525 | 3821 | 3143 | 48561 | 8 | 2 |
| Q25/2 | average_order_value {} | 58275 | 2984 | 3542 | 51749 | 10 | 1 |
| Q31/1 | net_revenue {} | 0 | 0 | 0 | 0 | 0 | 0 |
| S01A/1 | net_revenue {} | 19550 | 1240 | 1093 | 17217 | 5 | 1 |
| S01B/1 | net_revenue {} | 35975 | 2581 | 2050 | 31344 | 3 | 1 |

## Selected manual calculations from the canonical contribution sheet

January North has exactly five eligible order IDs: `o0000`, `o0008`, `o0009`,
`o0028`, `o0108`. Its eight item gross amounts are
`1000 + 2150 + 1000 + 3750 + 1500 + 1500 + 2150 + 6500 = 19550` cents.
The line discounts are `0 + 215 + 100 + 375 + 75 + 150 + 0 + 325 = 1240`;
approved USD refunds are `250 + 843 = 1093`. Thus net is
`19550 - 1240 - 1093 = 17217` cents, or **$172.17**. Aggregate AOV is
`17217 / (100 × 5) = 34.434`, final HALF_UP **$34.43**. Only `o0009` has
a received return, giving `1/5 = 0.200000`. Counting eight item rows would
produce the wrong order count and denominator.

January South has three eligible order IDs: `o0004`, `o0005`, `o0113`. Gross is
`3525 + 3250 + 3525 + 7050 + 5400 + 2425 + 8925 + 1875 = 35975` cents;
discounts `352 + 0 + 352 + 352 + 540 + 0 + 892 + 93 = 2581`; refunds
`812 + 793 + 445 = 2050`. Net is `35975 - 2581 - 2050 = 31344` cents,
or **$313.44**, with AOV `$313.44 / 3 = $104.48` and one received-return
order (`o0005`), giving **0.333333**. The combined January AOV is
`(17217 + 31344) / (100 × (5 + 3)) = 60.70125`, or **$60.70**;
averaging the two regional AOVs would incorrectly yield $69.455.

The source-cohort anchors confirm the refund/return distinction without using
an unsupported order-ID query:

- Q22's January 1 North/online cohort contains `o0000` only:
  `1000 - 0 - 250 = 750` cents, **$7.50**. It has a refund and no received return.
- Q23's January 10 North/online cohort contains `o0009` only:
  `1500 - 75 - 0 = 1425` cents; one of one orders has a received return, **1.000000**.
  It has no approved refund.
- Q18's March 31 cohort contains `o0089` only. Its three lines contribute
  `1325 - 66 = 1259`, `4850 - 1212 = 3638`, and `6450 - 322 = 6128` cents.
  Sum `1259 + 3638 + 6128 = 11025`, **$110.25**. A received return is on its
  first item while the approved refund is on the second; the order counts once.

For the complete authorized January–March cohort, gross **188400** minus
discounts **10755** minus approved refunds **10942** is net **166703** cents
(**$1667.03**). There are **27** eligible distinct orders, so AOV is
`166703/2700 = 61.741851...`, final **$61.74**. Four distinct returned orders
give `4/27 = .148148148...`, final **0.148148**. Inventory counts for all tenants
and regions (240 orders and 480 items) are deliberately different from these
authorized eligible counts.

Q15/Q16's selected boundary cohorts happen to be empty for this tenant/region
scope, so both monetary results are **$0.00**. Positive inclusive-start and
exclusive-end behavior is independently proven with handwritten boundary records
in `tests/test_retail_oracle.py`; the retail goldens are not altered to manufacture
a nonzero boundary example. Q19/Q20/Q21 separately prove scalar zero, nullable
zero denominator, and grouped empty output. These are frozen expected outcomes,
not claims that the deployed agent has answered the retail suite yet.
