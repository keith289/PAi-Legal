# PAi Parliament Handoff Contract

## Purpose

PAi Claims and PAi Legal are two Parliaments over one user-owned case state. The handoff is a change of analytical role, not a conversion of evidence and not a new truth system.

## Base-record rule

`case_graph.json` in the PAi Claims shared workspace is the base graph. PAi Legal opens it read-only and verifies its SHA-256 before and after linking. PAi Legal does not rewrite Claims nodes, edges, brackets, provenance, evidence IDs, values, reasons, or history.

## Atomic preservation

Each Claims node/edge is projected into the Legal reasoning corpus with:

- original node/edge ID;
- original statement/relation;
- current source bracket;
- underlying four-position Trust Lock;
- contradiction state when present;
- source evidence IDs;
- provenance roots;
- reason/basis;
- full promotion/correction/contradiction history;
- RPM channel when present.

`CONTRADICTED` remains an explicit source state. Because contradiction is orthogonal to the four-position Trust Lock, Legal also retains the last non-contradicted Trust Lock from the node history instead of inventing a promotion or demotion.

## Receiving-Parliament rule

PAi Legal may create legal propositions, element relationships, authorities, procedural events, draft statements, and other Legal-specific nodes. Those additions are written to `pai_legal/legal_graph_extensions.json` and can reference Claims IDs. They do not mutate the Claims base graph.

## No-promotion rule

Relational pressure, recurrence, AI output, drafting quality, or a persuasive legal theory cannot promote an incoming Claims Trust Lock. Independent corroboration must be attached to the specific atomic proposition whose epistemic state is changing.

## Shared-workspace layout

The Claims root remains user-owned:

- `pai_case_manifest.json`
- `claim.json`
- `case_graph.json`
- `audit/`
- `pai_legal/`

PAi Legal places its overlay inside `pai_legal/` and records only a link in its local `linked_claims.json` registry. The overlay can be regenerated from the base graph plus Legal extensions.

## Commerce and handoff

A Claims handoff counts as a PAi Legal case for access purposes:

- first PAi Legal case: free;
- additional cases: `pai-legal-single-case` Store-managed consumable;
- active `pai-legal-annual`: unlimited case creation while active.

A paid case credit is fulfilled only after the Legal case/overlay has been created successfully. Re-opening a workspace that is already linked is not a new case and does not reserve, purchase, or consume another credit.
