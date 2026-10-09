# PAi Legal 0.9.7.0 — Microsoft commerce + hardened Parliament handoff

- First PAi Legal case is free.
- Additional case uses Microsoft Store-managed consumable `pai-legal-single-case` ($50 configured in Partner Center).
- Annual access uses `pai-legal-annual` ($400/year configured in Partner Center).
- Offline annual cache is bounded to 7 days after a successful Store verification and rejects meaningful system-clock rollback.
- Claims Parliament handoff is read-only and preserves atomic brackets, provenance, relationships, contradictions, and promotion history.
- PAi Legal writes its own propositions to a separate legal extension graph and never rewrites the Claims base graph.
- Handoff requires a fresh PAi Claims 1.3.2+ persisted graph with matching state revision and claim-file SHA-256. Older/stale graph shells are refused loudly.
- Production patching is guarded: the kit requires an exact 0.9.6.0 build version seam, captures SHA-256 input hashes, and refuses ambiguous/mismatched source folders.
