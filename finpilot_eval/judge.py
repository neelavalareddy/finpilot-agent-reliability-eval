"""Two-layer judge.

Layer A: deterministic extraction accuracy vs planted ground truth.
    identifiers: exact match; currency: |diff| <= $1.00; percent: |diff| <= 0.05 pct-pt.
    A field whose truth is null is correct only if the agent also reports null (missing).
Layer B: rule-based reconciliation quality: restatement flagged? distribution reconciled
    against the ledger? every reported number cited to a valid source?
"""
from dataclasses import dataclass

from .dataset import ID_FIELDS, NUM_FIELDS, numbers_in

CURRENCY_TOL = 1.0
PERCENT_TOL = 0.05


def field_correct(field, truth_val, agent_val):
    if truth_val is None or agent_val is None:
        return truth_val is None and agent_val is None
    if field in ID_FIELDS:
        return agent_val == truth_val
    tol = PERCENT_TOL if field == "net_return_pct" else CURRENCY_TOL
    return abs(agent_val - truth_val) <= tol


def valid_citation(source, value, documents):
    """Source must be a real document containing the value (zero is trivially derivable)."""
    if source not in documents:
        return False
    if value == 0:
        return True
    return round(value, 2) in numbers_in(documents[source])


@dataclass
class DocScore:
    doc_id: str
    institution: str
    fields_correct: int
    fields_total: int
    reported: int
    hallucinated: int
    cited_valid: int
    ledger_checked: int
    ledger_mismatch: int
    restatement_applicable: int
    restatement_flagged: int
    dist_applicable: int
    dist_reconciled: int


def _ledger_match(value, ledger_val):
    return value is not None and abs(value - ledger_val) <= CURRENCY_TOL


def score_document(doc_id, output, truth_doc, documents, ledger_entry, all_numbers):
    correct = 0
    total = len(ID_FIELDS) + len(NUM_FIELDS)
    for f in ID_FIELDS:
        if field_correct(f, truth_doc[f], output.get(f)):
            correct += 1
    reported = halluc = cited = 0
    values = {}
    for f in NUM_FIELDS:
        entry = output["fields"].get(f, {})
        v, src = entry.get("value"), entry.get("source")
        values[f] = v
        if field_correct(f, truth_doc["fields"][f], v):
            correct += 1
        if v is not None:
            reported += 1
            if v != 0 and round(v, 2) not in all_numbers:
                halluc += 1
            if valid_citation(src, v, documents):
                cited += 1

    checked = mismatch = 0
    if ledger_entry:
        checked = 1
        ok = (_ledger_match(values["contributions"], ledger_entry["contributions"])
              and _ledger_match(values["distributions"], ledger_entry["distributions"]))
        mismatch = 0 if ok else 1

    traps = truth_doc.get("traps", [])
    flags = output.get("flags", {})
    r_app = 1 if "restatement" in traps else 0
    d_app = 1 if "ambiguous_distribution" in traps else 0
    dist_ok = field_correct("distributions", truth_doc["fields"]["distributions"], values["distributions"])
    return DocScore(
        doc_id=doc_id, institution=truth_doc["institution"],
        fields_correct=correct, fields_total=total,
        reported=reported, hallucinated=halluc, cited_valid=cited,
        ledger_checked=checked, ledger_mismatch=mismatch,
        restatement_applicable=r_app,
        restatement_flagged=1 if (r_app and flags.get("restatement_flagged")) else 0,
        dist_applicable=d_app,
        dist_reconciled=1 if (d_app and flags.get("distribution_reconciled") and dist_ok) else 0,
    )


def evaluate_agent(agent, dataset):
    all_numbers = dataset.all_numbers()
    registry = dataset.registry
    scores = []
    for doc_id, truth_doc in dataset.truth.items():
        ledger_entry = dataset.ledger.get(doc_id)
        context = {"registry": registry, "ledger": ledger_entry}
        output = agent.extract(doc_id, dataset.documents[doc_id], context)
        scores.append(score_document(doc_id, output, truth_doc, dataset.documents,
                                     ledger_entry, all_numbers))
    return scores


def _pct(n, d):
    return None if d == 0 else round(100.0 * n / d, 1)


def aggregate(scores):
    s = lambda attr: sum(getattr(x, attr) for x in scores)
    return {
        "docs": len(scores),
        "extraction_accuracy": _pct(s("fields_correct"), s("fields_total")),
        "hallucination_rate": _pct(s("hallucinated"), s("reported")),
        "reconciliation_error_rate": _pct(s("ledger_mismatch"), s("ledger_checked")),
        "traceability": _pct(s("cited_valid"), s("reported")),
        "restatement_flag_rate": _pct(s("restatement_flagged"), s("restatement_applicable")),
        "distribution_reconciled_rate": _pct(s("dist_reconciled"), s("dist_applicable")),
    }
