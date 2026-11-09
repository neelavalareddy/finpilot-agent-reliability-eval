# Finpilot agent reliability eval harness (prototype)

An offline, stdlib-only Python harness that measures how accurately an AI agent **extracts, reconciles and reports numbers** from institutional fund documents. Everything is **SYNTHETIC**: fictional institutions, funds and figures. No network, no LLM calls, no randomness.

> Status note: this code was written in an environment without code execution. It has not been run by its author; run the tests and demo yourself (below). `sample_report.md` is a placeholder until you run `python3 demo.py`.

## What it measures
Headline metrics, overall and per institution, for each agent:
- **Extraction accuracy %** — Layer A: per-field match vs planted ground truth (7 fields/doc: fund ID, fund name, NAV, contributions, distributions, net management fee, net return). Identifiers exact; currency within $1; percent within 0.05 pt. A genuinely absent field is correct only if reported as missing.
- **Hallucination rate %** — reported non-zero figures appearing in *no* source document.
- **Reconciliation error rate %** — documents whose reported contributions/distributions disagree with the ledger.
- **Traceability %** — reported numbers whose cited source exists and contains that number.
- Layer B extras: restatement flagged? ambiguous distribution reconciled against the ledger?

## Run
From this folder (Python 3.8+):
```
python3 -m unittest discover -s tests -t .
python3 demo.py          # prints the metrics table, writes sample_report.md
```

## Dataset (`data/`, SYNTHETIC)
12 documents, 4 per fictional institution: Lakeshore Children's Hospital Foundation (`hosp_*`), Cascadia State Employees Pension (`pen_*`), Whitmore University Endowment (`univ_*`). Types: quarterly manager reports, capital-call notices, distribution notices, manager letters. `ground_truth.json` holds planted truth; `ledger.json` holds fictional ledger totals. Simplification: every document carries a "Fund Summary" with the same five fields, so agents are scored on a uniform schema.

## Traps and why
| Trap | Doc | Why it exists |
|---|---|---|
| Restated figure | `hosp_03` | Original and restated NAV both appear; boards need the restated one, and the agent should flag it. |
| Gross vs net fee | `pen_01` | Reporting gross fee overstates cost to the investor. Truth = net. |
| Distribution that reads like a contribution | `hosp_04` | Direction of cash flow misclassified silently corrupts ledgers. Truth = distribution. |
| Near-identical fund names | `pen_03` / `pen_04` | The letter for Fund II includes Fund I's figures first; agents must not swap them. |
| Missing page | `univ_03` | Fee and return are on a page not received; correct behavior is to report them missing, not invent them. |

## Reference agents
`CarefulAgent` handles every trap and cites the source document per number. `SloppyAgent` takes the first figure, the gross fee, calls cash movements contributions, matches funds by name prefix, invents values for missing fields (fee = 1.25% of NAV, return = 7.25%) and cites nothing. Both are regex rule-based and deterministic.

## Pointing the harness at your own agents
Implement the interface documented at the top of `finpilot_eval/agents.py`: an object with `name` and `extract(doc_id, text, context)` returning fund ID/name plus, per field, `{value, source}` and the two flags. Then `build_results(agents=[YourAgent()])` (see `finpilot_eval/report.py`). To use your own documents, add text files plus matching `ground_truth.json` / `ledger.json` entries and pass `load_dataset(data_dir)`. A real LLM agent can wrap its call inside `extract`; the judge is unchanged.

## Honest limits
- Synthetic, tidy, regex-friendly documents: this validates the **eval method**, not any production agent's accuracy.
- The reference agents are strawmen designed to bracket the metric range; the 100% / low scores are by construction.
- Ledger reconciliation here is per-document equality, far simpler than real multi-period reconciliation.
- Tolerances and the 22-char name-prefix confusion rule are illustrative choices.
- Zero values are treated as trivially derivable (not counted as hallucinations).
