# HM-Arch sidecar protocol (JSONL stdio)

Stable contract between a host memory plugin (for example an OpenClaw plugin) and
the HM-Arch Python sidecar process. The protocol is **agent-agnostic**: it
describes process IPC only and does not embed OpenClaw-, Codex-, or Hermes-specific
fields in HM-Arch core APIs.

Golden fixtures live in [`fixtures/sidecar-protocol/`](../fixtures/sidecar-protocol/).
Python helpers: `hm_arch.integrations.sidecar`. TypeScript helpers:
`packages/installer/src/sidecar-protocol.ts`.

## Transport

- One UTF-8 JSON object per line on **stdin** (client → sidecar) and **stdout**
  (sidecar → client).
- Lines are delimited by `\n`. Empty lines are ignored.
- **stderr** is reserved for human-readable logs and is not part of the contract.
- The sidecar process is long-lived: `initialize` opens resources, `shutdown`
  releases them.

## Envelope

### Request

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocol_version` | string | yes | Client protocol version (`MAJOR.MINOR`, e.g. `"1.0"`) |
| `correlation_id` | string | yes | Opaque id echoed on the matching response |
| `operation` | string | yes | One of the operations below |
| `timeout_ms` | integer | no | Client hint; sidecar should abort work and return `TIMEOUT` when exceeded |
| `params` | object | yes | Operation-specific payload (may be `{}`) |

### Response

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocol_version` | string | yes | Negotiated protocol version for this session |
| `correlation_id` | string | yes | Echo of the request `correlation_id` |
| `operation` | string | yes | Echo of the request `operation` |
| `ok` | boolean | yes | `true` when the operation completed successfully |
| `result` | object | yes | Operation result; safe empty defaults when `ok` is `false` |
| `telemetry` | object | no | Benchmark fields (see Telemetry) |
| `error` | object \| null | yes | Structured error when `ok` is `false`, else `null` |

### Structured error

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | yes | Machine-readable code (see Error codes) |
| `message` | string | yes | Human-readable summary |
| `retryable` | boolean | yes | Whether the client may retry the same request |
| `details` | object | no | Optional diagnostic map |

## Protocol versioning

Versions use `MAJOR.MINOR` strings.

- **Major** must match for compatibility. A `1.x` client may talk to a `1.y`
  server.
- On `initialize`, the server returns `negotiated_protocol_version` =
  `min(client.protocol_version, server.protocol_version)` using semver ordering
  on `MAJOR.MINOR`.
- Servers must accept all minor versions within the same major and must not
  remove or change the meaning of existing fields within a major version.
- New optional request/response fields may be added in minor releases.
- Clients must ignore unknown response fields.

Current version: **`1.0`**.

## Capability negotiation

During `initialize`, the client sends `client_capabilities` (string tags). The
server returns:

- `server_capabilities` — features this sidecar build supports
- `negotiated_capabilities` — intersection of client and server tags

Capability tags are opaque protocol extensions (for example `telemetry.v1`,
`forget.by_query.v1`). Unsupported tags are ignored; they must not fail
initialization.

## Operations

| Operation | Purpose | Fail-open |
|-----------|---------|-----------|
| `initialize` | Open database, negotiate version and capabilities | no |
| `health` | Liveness and optional deep diagnostics | no |
| `search` | Recall relevant memory for a query | **yes** |
| `remember` | Persist arbitrary memory content | **yes** |
| `forget` | Forget by id or query | no |
| `record_turn` | Persist a completed user/assistant turn | **yes** |
| `consolidate` | Run offline sleep consolidation | no |
| `shutdown` | Flush and release resources | no |

### `initialize`

**params**

| Field | Type | Required |
|-------|------|----------|
| `db_path` | string | yes |
| `config` | object | no |
| `client_capabilities` | string[] | no |

**result**

| Field | Type | Description |
|-------|------|-------------|
| `ready` | boolean | Sidecar accepted the session |
| `negotiated_protocol_version` | string | Effective protocol version |
| `server_capabilities` | string[] | Supported capability tags |
| `negotiated_capabilities` | string[] | Intersection with client |
| `db_path` | string | Resolved database path |

### `health`

**params**

| Field | Type | Required |
|-------|------|----------|
| `deep` | boolean | no — when `true`, include storage stats |

**result**

| Field | Type |
|-------|------|
| `status` | `"healthy"` \| `"degraded"` \| `"unhealthy"` |
| `db_reachable` | boolean |
| `stats` | object (when `deep` is true) |

### `search` (fail-open)

**params**

| Field | Type | Required |
|-------|------|----------|
| `query` | string | yes |
| `top_k` | integer | no (default 5) |
| `session_id` | string | no |
| `max_context_chars` | integer | no |

**result**

| Field | Type |
|-------|------|
| `context` | string |
| `hits` | array of `{ memory_id, layer, content, score, retention }` |
| `result_count` | integer |
| `truncated` | boolean |

On failure: `ok=false`, empty `context`, `result_count=0`, `hits=[]`,
`truncated=false`. The host agent must continue.

### `remember` (fail-open)

**params**

| Field | Type | Required |
|-------|------|----------|
| `content` | string | yes |
| `event_type` | string | no |
| `importance` | number | no |
| `metadata` | object | no |
| `session_id` | string | no |

**result**

| Field | Type |
|-------|------|
| `memory_id` | string \| null |
| `recorded` | boolean |

On failure: `ok=false`, `memory_id=null`, `recorded=false`.

### `forget`

**params** — at least one of:

| Field | Type |
|-------|------|
| `memory_ids` | string[] |
| `query` | string |

**result**

| Field | Type |
|-------|------|
| `forgotten_count` | integer |
| `memory_ids` | string[] |

### `record_turn` (fail-open)

**params**

| Field | Type | Required |
|-------|------|----------|
| `user_message` | string | no* |
| `agent_message` | string | no* |
| `session_id` | string | no |

\* At least one non-empty message is required for a successful write.

**result**

| Field | Type |
|-------|------|
| `memory_ids` | string[] |
| `recorded_count` | integer |

On failure: `ok=false`, `memory_ids=[]`, `recorded_count=0`.

### `consolidate`

**params**

| Field | Type | Required |
|-------|------|----------|
| `force` | boolean | no |
| `session_id` | string | no |

**result**

| Field | Type |
|-------|------|
| `extracted_semantics` | integer |
| `merged_duplicates` | integer |
| `scheduled_reviews` | integer |
| `archived_to_l4` | integer |

### `shutdown`

**params**: `{}`

**result**

| Field | Type |
|-------|------|
| `shutdown_ack` | boolean |

## Telemetry

Optional `telemetry` object on responses. Benchmark runners should record:

| Field | Type | Operations |
|-------|------|------------|
| `query_latency_ms` | number | `search` |
| `hit_count` | integer | `search` |
| `returned_characters` | integer | `search` |
| `returned_tokens` | integer | `search` (approximate; whitespace token count) |
| `storage_latency_ms` | number | `remember`, `record_turn` |

Omitted fields mean the sidecar did not measure that metric.

## Error codes

| Code | Typical use | Retryable |
|------|-------------|-----------|
| `VALIDATION_ERROR` | Malformed envelope or params | false |
| `UNSUPPORTED_OPERATION` | Unknown `operation` | false |
| `UNSUPPORTED_VERSION` | Incompatible `protocol_version` major | false |
| `NOT_INITIALIZED` | Operation before successful `initialize` | true |
| `TIMEOUT` | Exceeded `timeout_ms` | true |
| `STORAGE_ERROR` | SQLite / IO failure | varies |
| `INTERNAL_ERROR` | Unexpected sidecar failure | true |

Fail-open operations (`search`, `remember`, `record_turn`) should prefer
`ok=false` with safe empty `result` values over process exit. Use
`STORAGE_ERROR` with `retryable=true` when appropriate.

## Relationship to the adapter protocol

`hm_arch.integrations.protocol` defines the older single-shot JSON adapter
(`recall` / `record` / `consolidate`) used by Codex and Claude Code hooks.
The sidecar protocol is the long-lived stdio contract for plugin hosts. Mapping:

| Sidecar | Adapter |
|---------|---------|
| `search` | `recall` |
| `record_turn` | `record` |
| `consolidate` | `consolidate` |

Implementations may translate between them inside integration layers; HM-Arch
core (`HMArch`) remains unaware of either wire format.

## Mock development

1. Load golden fixtures from `fixtures/sidecar-protocol/golden/`.
2. Parse requests with `parse_sidecar_request` (Python) or `parseSidecarRequest`
   (TypeScript).
3. Return canned responses from fixtures without starting SQLite.
4. Assert round-trip shape with `tests/test_integrations_sidecar_protocol.py` and
   `packages/installer/test/sidecar-protocol.test.ts`.
