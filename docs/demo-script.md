# Demo script

Two minutes, one take, no slides. The point is to show the loop, not to tour every menu. Record at 1440x900 or larger; keep the queue and the selected packet visible together.

The numbers below are from the seeded bundle. If a live run differs, say the number on screen instead of the number here.

## Before recording

1. Import the pod and open the settlement desk in a clean browser window.
2. Run the settlement cycle once and wait for the four new packets to finish reviewing.
3. Confirm the queue shows the seeded paid history, Mira and the Tides on hold, and the new packets in Needs a decision.
4. Confirm the desk is assigned to you (the header says so, or the approval card says "Assigned to").
5. Close every other tab. Hide bookmarks and the dock.
6. Check the screen reader line at the bottom of the packet, if the app shows one, so the audience can follow the amounts.

## The take

**0:00 - 0:12. The problem.**

On screen: the queue.

Say: "A venue settles an artist after every show. Ticket exports, receipts, a deal, and a number that has to be right. This is Loadout, a Lemma pod that turns that into one packet and one human decision."

**0:12 - 0:38. The live review.**

Click Fable & Stone.

Say: "Fable and Stone just came through the cycle. The reviewer read one fixed packet: ticket rows, expenses, the deal, and a fresh recomputation of the money. It found 22 comps against an allowance of 12, a block. The payout of $2,018.90 is arithmetically correct. The packet is still not payable."

Point at the block finding, then at the calculated payout.

Say: "The agent did not change the number. It cannot. It has no tools and no grants. Its only input is the packet, and its only output is a recommendation."

**0:38 - 0:55. The human gate.**

Scroll to Your call. Click Hold. Add a note such as "Hold until the comp count is reviewed."

Say: "The recommendation is advice. I can approve, change the amount with a reason, or hold. The app submits the workflow's waiting form, so the decision stays inside the workflow instead of becoming a direct database write."

Submit the hold.

**0:55 - 1:15. A clean packet.**

Click Rookery.

Say: "Rookery is clean. Both channels are present, fees are four percent, every receipt is attached, and the deal math ties out. The reviewer recommends approval. The decision is still mine."

Click Approve, leave the amount unchanged, and submit.

Say: "Approved. It stays in Needs you until the transfer reference is recorded."

**1:15 - 1:32. The payment close.**

Open the approved Rookery packet. Enter a reference such as `ACH-261023-01`. Click Record payment.

Say: "A payout cannot be marked paid unless it was approved. Once the reference is in, the settlement is closed. A paid settlement can never be reopened."

**1:32 - 1:48. The trail.**

Scroll to Activity.

Say: "Prepared, reviewed, held, approved, paid with a bank reference. Every step is on one trail. The function supplied arithmetic; the reviewer supplied judgment; the manager supplied the decision."

**1:48 - 2:00. The close.**

Return to the queue, filter All.

Say: "Loadout is a complete Lemma pod: seven tables, six functions, one toolless reviewer, two workflows, and the desk. Import it, point it at a month of shows, and the next settlement starts itself."

Stop on the queue with the new paid row visible.

## If something goes wrong

- **The cycle prepares nothing.** The four shows may already be settled from a previous take. Reset the pod or run against a fresh import.
- **The review card is empty.** The agent run may still be in flight. Wait for the card; do not submit a form that has no findings.
- **The form says "No open form found."** Refresh once. If it persists, the run was answered in another window or the wait expired; reopen the settlement with a reason.
- **The approval is assigned to someone else.** Change `settings.approval_member_id` in the data view, or reopen the settlement after changing it.
- **A number on screen differs.** Read the screen, not this script. The story is the loop, not the seed.

## What not to do

- Do not narrate the table schema or the directory tree. The video is for the product, not the repository.
- Do not claim the agent moves money. It does not, and the demo is stronger because it does not.
- Do not skip the hold. The held packet is the reason the approval gate exists.
- Do not speed up the cycle with a cut that hides whether it ran. Let the toast and the new rows land.
