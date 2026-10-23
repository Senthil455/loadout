# Contributing to Loadout

This repository is a working Lemma pod. A change is complete when the bundle still imports and the settlement loop still holds: prepare, audit, decide, pay, reopen.

## Before opening a pull request

1. Validate the bundle structure:

   ```bash
   python tools/verify_bundle.py
   python -m pytest tests -q
   ```

2. Run a dry import if you have the Lemma CLI:

   ```bash
   lemma pods import . --dry-run
   ```

3. If you changed the seed inputs, regenerate the CSVs and rerun both checks:

   ```bash
   python tools/build_seed.py
   python tools/verify_bundle.py
   ```

4. If you changed the app, open it in a pod and exercise the four states: draft, awaiting approval, approved, paid. Check the held state and the reopen path too.

5. Keep credentials, connector accounts, environment ids, and real venue data out of the commit.

## What a good change looks like

- The arithmetic stays in one place. If the deal formula changes, change `tools/settlement_math.py` and `prepare_settlements` together, bump `calculation_version`, and add a test for the new rounding.
- The reviewer stays toolless and packet-only. A change that gives it toolsets, grants, function invocation, or a connector needs a stronger reason than convenience.
- A new status transition goes through a function and writes a `settlement_events` row in the same call. Status changes without an event make the trail lie.
- A new workflow branch has a default edge. The graph validator rejects a decision that can strand a run.
- A new table column is added to the table JSON, the seed CSV header, and the verifier's expected shape.

## Product rule

Prefer a durable record and an explicit human decision over invisible automation. The pod is allowed to prepare, calculate, and recommend. It is not allowed to move money or approve its own work.

## Reporting a problem

Open an issue with the state you were in, the settlement id, and the event trail if you have it. Do not include real artist names, bank references, or receipts.
