# Implementation notes

Notes for someone changing the pod, not for someone installing it. The README explains what the desk does; this file explains why the pieces are shaped the way they are and what will break if you move them.

## Bundle layout and import order

The importer builds resources in dependency order: tables, files, functions, agents, workflows, schedules, surfaces, apps. That order is why a function can reference a table by name and a workflow can reference an agent and a function without extra wiring.

`pod.json` carries `format_version: 3`. Table JSON uses `primary_key_column: "id"`; the importer adds the UUID primary key, so the CSV files do not need to invent one beyond the stable ids they already contain.

Files under `files/` are addressed by pod path, for example `/policy/settlement-policy.md`. The agent's grant is on the `/policy` folder, not on individual files. `.files.json` lists the files for search; `.folder.json` describes the folder. Both are metadata, not content.

## The write path

There are six functions. Five own a state transition; `build_review_packet` owns the read-only evidence assembly that runs between the gate and the agent:

| Function | From | To | Refuses |
|---|---|---|---|
| `prepare_settlements` | a played show with no settlement | `draft` plus an open review request | nothing; it skips what is already settled |
| `attach_review` | `draft` | `awaiting_approval` | a closed request, or a settlement already approved, paid, or held |
| `record_review` | `awaiting_approval` | `approved` or `held` | a payout change without a note, a closed request, any other status |
| `mark_paid` | `approved` | `paid` | anything not approved, a zero payout, a missing reference |
| `reopen_settlement` | `held`, `approved`, `draft`, `awaiting_approval` | `draft` plus a fresh request | `paid`, or a settlement that already has an open request |

Every transition writes a `settlement_events` row in the same function call. The event is the audit trail; the settlement row is the current state. The app reads both, so a status without an explanation is visible as a gap.

`prepare_settlements` is safe to run repeatedly. It reads the existing settlements into a map by `show_id` and only creates a row when none exists. If it finds a `draft` with no open request, it inserts a fresh request and reports the count as `recovered` instead of silently skipping it. That is the repair path for a partial write or an interrupted import.

`attach_review` treats `held` as a decided state, not a reviewable one. A late review that arrives after a hold closes its request and writes a `review_ready` event saying so; it does not overwrite the hold. This matters because the approval workflow can be in flight when a manager holds from another tab.

`record_review` is idempotent after a decision. If the settlement is already `approved`, `paid`, or `held`, it closes any still-open request and returns the stored decision with `already_recorded: true`. The common case is a retried form submission after a timeout.

## The workflow split

`settlement-cycle` is a one-node scheduled workflow: call `prepare_settlements`, end. It is capped at one concurrent run in both the workflow and the schedule config. A second run would do the same reads and the same upserts, but the cap keeps the cycle from stacking up when a run is slow.

`settlement-approval` starts on `review_requests` INSERT:

1. `gate_request` checks that the inserted row is actually open. The trigger fires for any insert, including a row created by a repair path that is already closed.
2. `build_packet` calls `build_review_packet`, which reads the seven source tables and returns one packet with the stored settlement, the raw rows, the audit trail, and a fresh recomputation of the deal math.
3. `review` calls the agent with the request id, the settlement id, and that packet. The agent has no toolsets and no grants, so the packet is the entire observable world.
4. `attach` calls `attach_review`, which stores the snapshot, moves the settlement to `awaiting_approval`, and returns `can_review`, the payout, the artist, and the configured approver.
5. `route_review` stops when the review arrived too late to matter.
6. `route_assignee` chooses between two form nodes. `approval_assigned` uses `assignee_pod_member_id_expression`; `approval_open` has no assignee so any pod member can answer.
7. The form returns `decision`, `approved_payout_cents`, `note`, and `approver_email`. A decision node routes approve to `record_approval` and everything else to `record_hold`.
8. The matching `record_review` call writes the decision and closes the request.

The two form nodes exist because an empty `settings.approval_member_id` cannot be passed to `assignee_pod_member_id_expression`. The form executor resolves the expression and rejects anything that is not a UUID. A blank string would fail the node, not fall back. The decision node tests truthiness instead, so an unconfigured desk takes the unassigned branch and the workflow still completes.

The app adds `approver_email` to the form payload. The form schema carries it as an optional string, and the workflow maps it through both form paths. `record_review` uses it for `approved_by` and falls back to the workflow run identity when the form is answered somewhere else. Without that field, a workflow function would credit the pod owner because it runs as `run.user_id`, not as the person who submitted the form.

## The arithmetic and its snapshot

`tools/settlement_math.py` is the canonical formula. `build_seed.py` imports it, and `prepare_settlements` carries the same operations in its own code because a function bundle cannot import a repository file at runtime. The two copies are checked by `tests/test_settlement_math.py` and by the seed verifier.

The order matters:

1. Gross ticket revenue is the sum of paid quantity times face value across channels.
2. Fees are subtracted to get net box office.
3. Recoupable expenses are summed before the cap.
4. The cap is applied with `min`, and the overage is stored separately.
5. The pool is net box office minus recouped, floored at zero.
6. The deal type selects the payout; VS takes the greater side.

Half-up rounding is `(amount * bps + 5000) // 10000`. Python's `round` is banker's rounding and would produce different cents on exact halves, so the code never uses it for money.

The settlement stores the inputs and the result: revenue, fees, net, recoupable total, cap, recouped, overage, pool, deal type, guarantee, basis points, and payout. `calculation_version` is a text field so a future formula can be distinguished from this one without guessing from timestamps.

## Why the agent cannot edit

The agent manifest declares `toolsets: []` and an empty `permissions.grants` list. It has no datastore access, no file access, no function invocation, and no connector. The only data it sees is the packet `build_review_packet` passes in, and its output is a JSON object validated against `output_schema`; `attach_review` is the only writer, and it writes a fixed set of fields.

This is deliberate. An agent with write access to `settlements` could fix a number it dislikes; an agent with generic read tools could review a different row than the one the workflow gated. The point of the second pair of eyes is that it sees exactly the evidence in front of the reviewer and cannot change it.

## The app's data flow

The app uses the browser SDK at `/public/sdk/lemma-client.js`. It reads:

- `settlements`, `shows`, and `settlement_events` with `records.listAll` so a full month is not truncated at the default page size.
- `settings` with `records.list` (one row expected).
- Pod members with `podMembers.list(podId)` to map ids and emails to names.
- Waiting runs with `workflows.runs.listInPod({ status: ["WAITING"] })`, then `workflows.runs.get` for each run.

The second call is necessary: the list response carries `waiting_on` and a title, but not the execution context. The full run carries `execution_context.attach.settlement_id`, which is how the app matches a waiting form to a settlement. A settlement can have at most one active approval because `reopen_settlement` refuses when a request is already open.

The app does not query the workflow by settlement id. Doing so would need an index the API does not expose; matching the small waiting set in the client is cheaper and works with the public API.

Form submission uses `workflows.runs.submitForm(runId, { node_id, inputs })`. The `node_id` must match `active_wait.node_id`; the engine rejects a mismatch. The app passes the wait's own node id, so the assigned and unassigned form paths both work without branching in the client.

The app polls every 22 seconds and also subscribes to `datastore.watchChanges` when the socket is available. The poll is the fallback, not the primary path; the watch is debounced so a burst of writes does not produce a burst of reads.

## Seed generation

`tools/build_seed.py` writes every `data.csv` from one deterministic script. It is the source of truth for the demo data. Changing a show, an expense, or a deal means editing the input tables at the top of the script and rerunning it, not hand-editing CSV rows.

The generator:

- uses stable UUIDs derived from the show and row identity, so re-imports upsert instead of duplicating;
- computes the settlement fields with `settlement_math`;
- writes a full ten-check review for each historical settlement, ordered blocks, watches, then passes;
- writes events in chronological order with the same timestamps as the settlement and request;
- writes paid rows with `approved_by` and a transfer reference, and the held row with no approval or payment fields.

Rerun it from the repository root:

```bash
python tools/build_seed.py
python tools/verify_bundle.py
```

## Failure modes worth knowing

**A review never arrives.** The settlement stays `draft`, the request stays open, and the app shows "In review." Check the agent run and the workspace model configuration. The form is not created until `attach_review` returns `can_review: true`.

**A form is answered twice.** The second submission gets a 409 from the workflow because the wait is no longer active. If a function retry happens after the first decision, `record_review` returns `already_recorded: true` rather than erroring.

**A paid settlement needs a correction.** It cannot be reopened. Record an adjustment outside the settlement and leave the original row intact; the alternative is a financial record that changes after the money moved.

**The approver leaves the pod.** The assigned form keeps the old pod member id and nobody can answer it. Change `settings.approval_member_id` and reopen the settlement; the new request routes to the new approver.

**The cap changes after preparation.** It does not affect the stored settlement. Reopen the settlement only if the deal itself was wrong; the reopen creates a new review against the same snapshot, and a changed deal needs a new settlement, not a quiet edit.
