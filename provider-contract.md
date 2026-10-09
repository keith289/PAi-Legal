# PAi Legal integration contract

PAi Legal owns its UI, ingestion, OCR, model installation, and local inference.
PAi and PAi LFM are not dependencies. PSi Legal is the only optional product
integration.

## PSi Legal

Preferred handoff: `http://127.0.0.1:<port>/v1/corpus/search`.
Fallback: read-only SQLite corpus shards exposed outside the PSi Legal MSIX
private LocalState boundary.

`psi-legal.json` may be published under the shared provider location:

```json
{
  "schema_version": 1,
  "product_id": "9NHNVPTD93XT",
  "api_url": "http://127.0.0.1:8082",
  "credential_name": "psi_legal_api_token",
  "corpus_roots": ["C:\\...\\corpus"],
  "shards": ["C:\\...\\casehold_rpm.db"]
}
```

The search service returns stored records, never generated citations. The URL
must be loopback-only and every request carries `Authorization: Bearer <token>`.
The provider manifest never contains the bearer token. The user stores it under
`credential_name` in PAi Legal's Windows DPAPI vault; a plaintext `api_token`
field is rejected.
Search terms are sent in a POST body so they do not enter URL logs:

`POST /v1/corpus/search`

```json
{"q":"summary judgment","limit":20,"jurisdiction":"GA","rpm_float":2,"rpm_mix":1,"rpm_stir":0,"rpm_signature":"hex","include":"rpm"}
```

```json
{"results":[{"source_id":"stored-row-id","title":"stored title","citation":"stored citation","excerpt":"stored excerpt","jurisdiction":"GA","year":2024,"flags":"","bracket":"UNVERIFIED","float_points":12,"mix_points":5,"stir_points":3,"total_pressure":24.5,"float_color":"GREEN","mix_color":"YELLOW","stir_color":"ORANGE","pattern_signature":"hex"}]}
```

The RPM fields are optional for older PSi Legal builds. Missing values resolve
downward to zero and `UNVERIFIED`; PAi Legal never infers a stronger bracket.
Original source text is never rewritten. Pressure and clarity describe pattern
structure, not truth, and cannot award `VALIDATED` status.

Development overrides: `PAI_LEGAL_AI_URL`, `PAI_LEGAL_LLAMA_SERVER`,
`PAI_LEGAL_AI_PORT`, `PSI_LEGAL_URL`, `PAI_PROVIDER_DIR`, and
`PSI_CORPUS_ROOTS`.
