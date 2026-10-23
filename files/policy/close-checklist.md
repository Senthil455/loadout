# Show close checklist

Use this order for every show. The settlement desk follows the same sequence,
and the audit trail names each step.

## 1. Close the ticket channels

- Export the online sales report after the show closes.
- Collect the door sheet from the closing manager.
- Record one `ticket_sales` row per channel with the paid count, face value,
  fees, comps, and the source file name.
- A channel with no source reference is not reconciled. A missing channel is a
  watch item; no sales rows at all is a block.

## 2. Enter the expenses

- Record every vendor, category, amount, and whether the expense is recoupable
  under the deal.
- Attach the invoice or receipt reference to every recoupable expense at or
  above the settings threshold.
- A recoupable expense below the threshold with no receipt is a watch item. At
  or above the threshold it is a block.
- Non-recoupable venue costs stay in the table for reporting but never touch the
  artist pool.

## 3. Reconcile the packet

Reconciled means all of the following are true:

- Both ticket channels have a source reference.
- The paid counts and comps match the exports.
- Every required receipt is present.
- The deal terms on the show match the terms on the settlement.
- The stored money fields equal a fresh run of the formula.

If any of those is false, the packet is not reconciled. Say which one and stop.

## 4. Prepare the settlement

`prepare_settlements` runs on the daily cycle, or from the desk when a show is
closed early. It creates one settlement per played show, snapshots the deal, and
opens one review request. It does not recompute an existing settlement, so a
reviewed number cannot change underneath the manager.

## 5. Audit the packet

The `settlement-reviewer` agent reads the policy, the deal guide, the packet,
and the earlier events. It returns ten checks with a recommendation. It cannot
approve, pay, or edit a row. A block always means hold; two or more watch items
also mean hold.

## 6. Approve or hold

The approval form goes to the configured desk member. If the desk has not been
claimed, any pod member can answer it. The manager can approve the calculated
amount, change it with a written reason, or hold the settlement.

A hold closes the review request and leaves no payable amount. The request can
be reopened after the missing document arrives.

## 7. Pay and close

When the bank confirms the transfer, record the payment reference with
`mark_paid`. Only an approved settlement can be paid. A paid settlement is
closed for good; a correction is a new adjustment, not a reopened payout.

## Who does what

| Step | Owner |
|---|---|
| Ticket exports and expense entry | Venue staff |
| Settlement math and cycle | `prepare_settlements` |
| Packet audit | `settlement-reviewer` |
| Payout decision | Venue manager |
| Transfer and payment reference | Venue manager |
| Reopen after a fix | Venue manager |
