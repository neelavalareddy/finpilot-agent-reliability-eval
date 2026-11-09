# data/ — SYNTHETIC

Everything here is **SYNTHETIC**. The institutions, funds, documents and figures are fictional and invented for this harness. Any resemblance to real entities is coincidental.

- `documents/*.txt` — 12 fake fund documents (4 per institution).
- `ground_truth.json` — planted truth per document (null = genuinely absent from the document).
- `ledger.json` — fictional per-document cash ledger totals used for reconciliation.

Traps: `hosp_03` restatement, `hosp_04` ambiguous distribution, `pen_01` gross vs net fee, `pen_04` near-identical fund names (vs `pen_03`), `univ_03` missing page.
