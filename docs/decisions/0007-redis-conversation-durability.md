# ADR 0007: Redis conversation durability

## Status

Accepted for M7.

## Decision

Keep the existing plain Redis 7 service. Implement the LangGraph BaseCheckpointSaver
contract using typed checkpoint hashes, a monotonic checkpoint index, parent links,
and deduplicated pending writes. Declare the checkpoint package directly and use an
explicit serializer allowlist for CommerceOps state types, without pickle fallback.

Store session ownership, debounced text fragments, message receipts, approvals, and
results in Redis. Use a stable hash of tenant and session as the graph thread ID.
Source message IDs remain part of normalized state and inspection output.
Serve inspection through GET /sessions/{session_id}/state.

Run a due-session worker in the API lifespan. Serialize sessions with renewable
Redis leases and token-checked Lua state updates. Consume approvals atomically
and validate their relationship to the active session before resuming.
Duplicate message IDs return receipts, while changed content under the same ID
is rejected. New messages cannot overwrite an unresolved approval.

Enable AOF with appendfsync always and a named Redis volume.

## Rationale

Checkpoint persistence alone does not preserve queued messages or establish who
may approve them. Persisting the complete intake boundary keeps ownership and
execution state aligned across API restarts and worker instances.
Plain Redis storage avoids requiring Redis Search/JSON modules or a different
deployment service for the MVP. The custom saver needs contract tests and ongoing
compatibility checks against the declared LangGraph checkpoint API.

## Recovery and limits

- Recover queued messages, saved final outcomes, and saved pending interrupts.
- Never automatically replay unfinished write nodes after a possible write.
- Report EXECUTION_INTERRUPTED and require inspection for uncertain outcomes.
- Scope every public inspection and approval to the trusted tenant and user.
- Lease renewal protects normal concurrent workers; fenced metadata updates reject stale owners.
- This is a single Redis deployment, not a guarantee under Redis failover or partitions.
- Redis and PostgreSQL have separate transactions; cross-store exactly-once execution is not claimed.
- Checkpoints and receipts currently have no automatic retention policy.
- Debounce aggregation supports text; media preprocessing is outside this milestone.

## Validation

Real Redis tests cover aggregation, deadline reset, immediate flush, preserved source
IDs, runtime restart, approval resume without replanning, competing workers, atomic
claims, tenant/user isolation, reused thread state, HTTP inspection, uncertain write
recovery, recovered interrupts, lease renewal, stale-owner fencing, and scoped deletion.
