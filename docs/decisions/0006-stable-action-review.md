# ADR 0006: Stable action review and one-use approval handles

## Status

Accepted as a corrective change to M6.

## Decision

Split planning and entity resolution, policy evaluation, human review, and write
execution into separate graph steps. Checkpoint resolved proposals and policy
decisions before the interrupt node. Execute only saved arguments after approval.

Collect proposals across specialists before any business write. Evaluate the
combined batch limit and include every covered action in a single review payload.
Rejecting the request prevents all its proposed writes.

Consume approval handles atomically under trusted tenant-and-user ownership.
Expose all graph interrupts and map decisions to their IDs. Issue a new handle
if a resumed graph pauses again. Do not automatically replay uncertain writes.

Use Overwrite to clear per-request list channels when a thread is reused.
Keep additive reducers for concurrent worker updates inside each request.

## Rationale

LangGraph replays an interrupted node from its beginning. Model calls and entity
lookups inside that node can change the proposed operation before the human's
answer is consumed. A saved proposal makes the approval refer to the exact
operation that was shown.

A check-then-resume sequence allows two concurrent HTTP calls to consume the
same approval. Atomic ownership validation and consumption prevent this race.
Interrupt ID maps prevent a response from being paired with the wrong branch.

## Trade-offs and limits

- Approval is for the displayed request batch; per-action editing is not supported.
- Service validation still checks the current tenant and business invariants.
- Approved tools have separate service transactions, not a shared rollback boundary.
- Claims and checkpoints remain process-local in M6; Redis durability is M7.
- A failure after a possible write requires inspection, rather than an automatic retry.
- LangGraph 1.x is required for explicit state overwrites and the supported interrupt API.

## Validation

Regression tests cover changed planner outputs, rejection, changed entity lookup
results, parallel actions, batch limits across specialists, concurrent decisions,
unauthorized users, uncertain failures, multiple interrupt IDs, new approval
handles, and collection resets when reusing a thread.
