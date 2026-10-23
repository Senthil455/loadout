# Settlement policy

The Lantern Room pays artists from the show's box office after the room's
recoupable expenses. This policy is the contract between the venue and the
settlement desk. `prepare_settlements` applies the arithmetic, the
`settlement-reviewer` agent audits the packet, and the venue manager approves the
transfer.

## Money rules

- All amounts are integer cents. Never store a rounded dollar amount in a money
  field.
- `ticket_revenue = sum(paid_quantity * face_value_cents)` across channels.
- `net_box_office = ticket_revenue - sum(fees_cents)`.
- `recoupable_total = sum(amount_cents)` for expenses with `recoupable = true`.
- `recouped = min(recoupable_total, expense_cap_cents)`.
- `over_cap = recoupable_total - recouped`. The venue absorbs the overage; the
  artist is never charged for it.
- `pool = max(0, net_box_office - recouped)`.
- `FLAT` pays the guarantee.
- `PERCENTAGE` pays `round_half_up(pool * percentage_bps / 10000)`.
- `VS` pays the greater of the guarantee and the percentage share.
- Round half up: `(pool * percentage_bps + 5000) // 10000`.
- Comps are tracked and never deducted from revenue. A comp is a seat the venue
  gave away, not a sale.

## Thresholds

| Check | Pass | Watch | Block |
|---|---|---|---|
| Processor fees | at or below 5.00% of gross | above 5.00% and at or below 8.00% | above 8.00% |
| Receipts | every recoupable expense at or above the settings threshold has a receipt | a recoupable expense below the threshold has no receipt | a recoupable expense at or above the threshold has no receipt |
| Recoup cap | recoupable total at or below the cap | over the cap by at most 20% | over the cap by more than 20% |
| Comps | at or below the settings allowance | over by at most 50% | over by more than 50% |
| Payout floor | payout is at least the guarantee on FLAT and VS; above zero on PERCENTAGE | - | below the floor |
| Prior payment | no other paid settlement for the show | - | another paid settlement exists |

The receipt threshold and comp allowance live in the `settings` row so the venue
can change them without editing the agent. The defaults are $250.00 per
recoupable expense and 12 comps per show.

## Decision rule

- Any block means hold.
- Two or more watch findings mean hold.
- Otherwise approve.

The recommendation is advice. The manager can approve, hold, or change the
amount. A changed amount needs a written note, and the note is stored on the
settlement and copied into the audit trail.

## What the agent may not do

The reviewer is toolless and packet-only. It receives one evidence packet and
has no datastore, file, function, or connector access. It cannot move money,
edit a settlement, close a request, or approve a payout. It must not invent a
row, a receipt, an amount, or a policy. If a source is missing, it names the
source and treats the gap as a block when this policy says so.

## Reopening and payment

A held settlement can be reopened after the packet is fixed. A paid settlement
cannot be reopened; a correction is a new adjustment, not a second payment. Only
an approved settlement can be marked paid, and a payment reference is required.
