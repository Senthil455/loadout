# Security

Do not open a public issue for a suspected security vulnerability.

Loadout handles settlement records, which means amounts, vendor names, and bank references. Treat them as financial data even when the seed is fictional.

Keep these out of the repository:

- API keys, model provider keys, and Lemma tokens
- Bank account numbers, routing numbers, and real transfer references
- Real artist contracts, receipts, and ticket exports
- Pod member ids, user ids, and workspace URLs tied to a live venue

The checked-in pod is designed to be bound to those resources after import. If you need to reproduce a problem, replace names and amounts with invented ones that preserve the shape of the record.

When reporting a vulnerability, include the affected resource, the trust boundary crossed, and a minimal reproduction that contains no real credentials or private data. If the issue involves the platform rather than this bundle, report it to the Lemma maintainers directly.
