# PAi Legal v0.9.6 — professional controls

This release keeps PAi Legal's deterministic findings, optional PSi Legal
retrieval, and separate external drafting layer. It adds a local professional
control plane around that architecture.

## Security and privacy

- OS-account role policy: owner, lawyer, paralegal, intake, and auditor.
- DPAPI-protected credentials and per-case audit integrity keys.
- Optional write blocking unless BitLocker protection is verified.
- Authenticated loopback integrations; plaintext provider-manifest tokens are rejected.
- The bundled local drafter is the only browser drafting page PAi Legal opens.

## Records governance

- HMAC-SHA256 audit chain plus protected rollback anchor.
- Retention date/basis, legal holds, hold release, and controlled disposition eligibility.
- Conflict-name screening across active and archived matters.
- AES-GCM encrypted, Scrypt-derived, manifest-verified case backup and restore.

## Filing and release gates

- Mechanical federal civil and Georgia Superior Court rule packs, dated to
  their official sources and always requiring current local-rule verification.
- Immutable GGUF revision and SHA-256 download verification.
- Optional MSIX signing, timestamping, and signature verification.

These controls are product safeguards, not a certification of compliance with
any firm's ethical, contractual, insurance, or regulatory obligations.
