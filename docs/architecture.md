# Architecture

## Boundaries

```mermaid
flowchart LR
    App[Trusted application context] --> Tools[Semantic tools and v1 contracts]
    Agent[Future Bedrock agent on AgentCore] --> Tools
    Tools --> Interface[SemanticAdapter]
    Interface --> Local[Local DuckDB adapter]
    Interface -. future .-> Athena[AWS governed metrics / Athena adapter]
    Interface -. future .-> Cube[Cube adapter]
    Local --> Data[Local Parquet retail tables]
```

The agent consumes backend-independent semantic contracts. AWS-specific and Cube-specific logic belongs in adapters. `contracts.py` and `adapter.py` must not import provider clients, DuckDB types, or SQL. Milestone 1 implements only the local execution path; there is no agent loop or deployed service yet.

The four semantic tools are `discover_metrics`, `describe_metric`, `query_metric`, and `discover_dimensions`. Metric definitions own calculations, allowed dimensions, relationships, filters, units, and time semantics. The catalog is the source of governed configuration; an adapter translates the supported calculation into backend execution rather than accepting a user expression.

`catalog.MetricSpecification` is internal execution configuration. `contracts.MetricDefinition` is the public business description produced by an explicit projection. Description and dimension-discovery responses include logical dimension names, business rules, units, the logical order-item grain, and order-date semantics. Executable expressions, source-table/column bindings, and tenant-scoped join keys stay in the catalog. Public response JSON schemas also omit those details; serialization exclusions alone would still advertise them to schema consumers.

## Contracts and authorization

Every request and response includes `api_version: "v1"`; incompatible changes require a new contract version. Unknown fields and unsupported versions are rejected. Dates are date objects or ISO `YYYY-MM-DD` strings, never timestamps. A date range is `[start, end)` with `start < end`. Decimal currency serializes as a string.

`AuthorizationContext` is passed separately by trusted application code and contains a principal, tenant, and explicit allowed regions. The context is never part of model-visible request schemas. Empty region scope denies all access. All four adapter methods check the context; query execution and dimension discovery also apply tenant and region restrictions. Requests cannot override these restrictions. The local CLI constructs its context as application configuration, not as command-line identity options.

This enforces a local trust boundary. Production must authenticate the application principal and derive tenant and region scope from verified claims or a policy service before constructing this context. A Pydantic object alone does not authenticate a user.

## Local storage and execution

Six Parquet files contain customers, products, orders, order items, payments, and refunds. Monetary values are signed 64-bit integer cents in storage. Order region and channel are historical attributes stored on the order, so customer changes cannot restate dimensions.

The adapter loads a snapshot into its own in-memory DuckDB connection. Exact repeated records collapse by business key; contradictory records with the same business key are rejected. Approved refunds aggregate once per order item before joining eligible orders and items. Payments and products are not joined into the revenue aggregation, avoiding fanout. Authorization predicates and request filter values use bound parameters. SQL identifiers come only from the catalog's allowed dimensions.

Local snapshot ingestion assumes application-controlled Parquet. This milestone does not implement arbitrary uploads, schema migrations, streaming updates, warehouse governance, or a policy service. Reopen the adapter to observe changed files. Use its context manager to close the connection.

Ingestion requires the documented column names and storage types, nonnull fields except optional refund approval dates, nonnegative source amounts, positive item quantities, discounts no greater than line gross, and valid tenant-scoped relationships. Approved refunds require an approval date. These checks reject malformed snapshots rather than silently discarding records. Over-refunds can produce negative net revenue; there is no full ledger reconciliation or limit on refund totals in this milestone.

## Future integrations

The planned production path uses Amazon Bedrock, AgentCore, and AWS-native governed metrics through Athena, followed by Cube. Before implementing any external integration, validate SDK usage against current official documentation and record the documentation used. Provider-specific identity propagation, query lifecycle, credentials, and errors remain inside adapters or trusted hosting code. Do not make AWS calls during milestone 1.

For local implementation, official references checked on 2026-11-05 include [DuckDB's Python API](https://duckdb.org/docs/stable/clients/python/overview), [Pydantic configuration](https://docs.pydantic.dev/latest/api/config/), and [Poetry project configuration](https://python-poetry.org/docs/pyproject/).
