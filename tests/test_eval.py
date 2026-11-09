"""Deterministic, offline tests. All data is SYNTHETIC."""
import tempfile
import unittest
from pathlib import Path

from finpilot_eval.agents import CarefulAgent, SloppyAgent
from finpilot_eval.dataset import NUM_FIELDS, load_dataset, numbers_in
from finpilot_eval.judge import (aggregate, evaluate_agent, field_correct,
                                 score_document, valid_citation)
from finpilot_eval.report import build_results, render_markdown, render_table, write_report

DS = load_dataset()
CAREFUL, SLOPPY = CarefulAgent(), SloppyAgent()


def run(agent, doc_id):
    return agent.extract(doc_id, DS.documents[doc_id],
                         {"registry": DS.registry, "ledger": DS.ledger.get(doc_id)})


def val(out, field):
    return out["fields"][field]["value"]


class DatasetIntegrity(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(len(DS.truth), 12)
        self.assertEqual(len(DS.institutions), 3)
        for inst in DS.institutions:
            self.assertEqual(sum(1 for t in DS.truth.values() if t["institution"] == inst), 4)

    def test_every_doc_marked_synthetic(self):
        for doc_id, text in DS.documents.items():
            self.assertIn("SYNTHETIC", text.splitlines()[0], doc_id)

    def test_every_planted_figure_present_in_its_document(self):
        for doc_id, t in DS.truth.items():
            nums = numbers_in(DS.documents[doc_id])
            for f in NUM_FIELDS:
                v = t["fields"][f]
                if v:  # None and zero are not literal figures
                    self.assertIn(round(float(v), 2), nums, "%s %s" % (doc_id, f))
            self.assertIn(t["fund_id"], DS.documents[doc_id])
            self.assertIn(t["fund_name"], DS.documents[doc_id])

    def test_ledger_matches_truth(self):
        for doc_id, t in DS.truth.items():
            for f in ("contributions", "distributions"):
                self.assertEqual(DS.ledger[doc_id][f], t["fields"][f], (doc_id, f))

    def test_each_trap_present_exactly_once(self):
        traps = [x for t in DS.truth.values() for x in t["traps"]]
        self.assertEqual(sorted(traps), sorted(
            ["restatement", "gross_vs_net", "ambiguous_distribution", "near_identical_names", "missing_page"]))

    def test_restatement_doc(self):
        text = DS.documents["hosp_03"]
        self.assertIn("NAV (as originally reported): $18,900,000", text)
        self.assertEqual(DS.truth["hosp_03"]["fields"]["nav"], 18420000)

    def test_gross_net_doc(self):
        self.assertIn("(gross): $480,000", DS.documents["pen_01"])
        self.assertEqual(DS.truth["pen_01"]["fields"]["mgmt_fee_net"], 385000)

    def test_ambiguous_distribution_doc(self):
        self.assertNotIn("Distributions:", DS.documents["hosp_04"])
        self.assertEqual(DS.truth["hosp_04"]["fields"]["distributions"], 250000)
        self.assertEqual(DS.truth["hosp_04"]["fields"]["contributions"], 0)

    def test_near_identical_names(self):
        a, b = DS.truth["pen_03"]["fund_name"], DS.truth["pen_04"]["fund_name"]
        self.assertNotEqual(a, b)
        self.assertEqual(a[:22], b[:22])

    def test_missing_page_doc(self):
        t = DS.truth["univ_03"]["fields"]
        self.assertIsNone(t["mgmt_fee_net"])
        self.assertIsNone(t["net_return_pct"])
        self.assertNotIn("Management Fee", DS.documents["univ_03"])
        self.assertIn("NOT RECEIVED", DS.documents["univ_03"])


class CarefulTraps(unittest.TestCase):
    def test_restatement(self):
        out = run(CAREFUL, "hosp_03")
        self.assertEqual(val(out, "nav"), 18420000.0)
        self.assertTrue(out["flags"]["restatement_flagged"])

    def test_net_fee(self):
        self.assertEqual(val(run(CAREFUL, "pen_01"), "mgmt_fee_net"), 385000.0)

    def test_ambiguous_distribution(self):
        out = run(CAREFUL, "hosp_04")
        self.assertEqual(val(out, "distributions"), 250000.0)
        self.assertEqual(val(out, "contributions"), 0.0)
        self.assertTrue(out["flags"]["distribution_reconciled"])

    def test_near_identical_funds(self):
        out = run(CAREFUL, "pen_04")
        self.assertEqual(out["fund_id"], "PF-204")
        self.assertEqual(val(out, "nav"), 33700000.0)
        self.assertEqual(val(out, "net_return_pct"), 8.8)
        self.assertEqual(run(CAREFUL, "pen_03")["fund_id"], "PF-203")

    def test_missing_fields_reported_missing(self):
        out = run(CAREFUL, "univ_03")
        self.assertIsNone(val(out, "mgmt_fee_net"))
        self.assertIsNone(val(out, "net_return_pct"))
        self.assertEqual(val(out, "nav"), 38640000.0)

    def test_cites_every_reported_number(self):
        for doc_id in DS.truth:
            out = run(CAREFUL, doc_id)
            for f, e in out["fields"].items():
                if e["value"] is not None:
                    self.assertEqual(e["source"], doc_id, (doc_id, f))


class SloppyTraps(unittest.TestCase):
    def test_first_figure_not_restated(self):
        out = run(SLOPPY, "hosp_03")
        self.assertEqual(val(out, "nav"), 18900000.0)
        self.assertFalse(out["flags"]["restatement_flagged"])

    def test_gross_fee(self):
        self.assertEqual(val(run(SLOPPY, "pen_01"), "mgmt_fee_net"), 480000.0)

    def test_distribution_misclassified(self):
        out = run(SLOPPY, "hosp_04")
        self.assertEqual(val(out, "contributions"), 250000.0)
        self.assertEqual(val(out, "distributions"), 0.0)
        self.assertFalse(out["flags"]["distribution_reconciled"])

    def test_confuses_near_identical_funds(self):
        out = run(SLOPPY, "pen_04")
        self.assertEqual(out["fund_id"], "PF-203")
        self.assertEqual(val(out, "nav"), 29950000.0)

    def test_invents_missing_values(self):
        out = run(SLOPPY, "univ_03")
        self.assertEqual(val(out, "mgmt_fee_net"), 483000.0)
        self.assertEqual(val(out, "net_return_pct"), 7.25)
        self.assertNotIn(483000.0, DS.all_numbers())
        self.assertNotIn(7.25, DS.all_numbers())

    def test_no_citations(self):
        for doc_id in DS.truth:
            for e in run(SLOPPY, doc_id)["fields"].values():
                self.assertIsNone(e["source"])


class JudgeHandChecked(unittest.TestCase):
    def test_field_correct_tolerances(self):
        self.assertTrue(field_correct("nav", 100.0, 100.5))
        self.assertFalse(field_correct("nav", 100.0, 102.0))
        self.assertTrue(field_correct("net_return_pct", 8.4, 8.43))
        self.assertFalse(field_correct("net_return_pct", 8.4, 8.5))
        self.assertTrue(field_correct("fund_id", "A", "A"))
        self.assertFalse(field_correct("fund_id", "A", "B"))
        self.assertTrue(field_correct("mgmt_fee_net", None, None))
        self.assertFalse(field_correct("mgmt_fee_net", None, 5.0))
        self.assertFalse(field_correct("mgmt_fee_net", 5.0, None))

    def test_valid_citation(self):
        docs = {"d1": "NAV: $100"}
        self.assertTrue(valid_citation("d1", 100.0, docs))
        self.assertFalse(valid_citation("d1", 101.0, docs))
        self.assertFalse(valid_citation("d2", 100.0, docs))
        self.assertFalse(valid_citation(None, 100.0, docs))
        self.assertTrue(valid_citation("d1", 0.0, docs))

    def test_score_document_hand_checked(self):
        truth = {"institution": "X", "traps": [], "fund_id": "F1", "fund_name": "Fund One",
                 "fields": {"nav": 100.0, "contributions": 10.0, "distributions": 5.0,
                            "mgmt_fee_net": 1.0, "net_return_pct": None}}
        docs = {"d1": "NAV: $100\nContributions: $10\nDistributions: $5\nManagement Fee: $1"}
        out = {"fund_id": "F1", "fund_name": "Fund One", "flags": {}, "fields": {
            "nav": {"value": 100.0, "source": "d1"},
            "contributions": {"value": 10.0, "source": "d1"},
            "distributions": {"value": 6.0, "source": "d1"},
            "mgmt_fee_net": {"value": 1.0, "source": None},
            "net_return_pct": {"value": 7.25, "source": None}}}
        s = score_document("d1", out, truth, docs, {"contributions": 10, "distributions": 5},
                           numbers_in(docs["d1"]))
        self.assertEqual((s.fields_correct, s.fields_total), (5, 7))
        self.assertEqual(s.reported, 5)
        self.assertEqual(s.hallucinated, 2)   # 6 and 7.25
        self.assertEqual(s.cited_valid, 2)    # nav, contributions
        self.assertEqual((s.ledger_checked, s.ledger_mismatch), (1, 1))

    def test_aggregate_percentages(self):
        scores = evaluate_agent(CAREFUL, DS)[:1]
        m = aggregate(scores)
        self.assertEqual(m["extraction_accuracy"], 100.0)
        self.assertIsNone(m["restatement_flag_rate"])  # not applicable to hosp_01


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = build_results(DS)

    def test_careful_is_perfect(self):
        m = self.results["careful"]["overall"]
        self.assertEqual(m["extraction_accuracy"], 100.0)
        self.assertEqual(m["hallucination_rate"], 0.0)
        self.assertEqual(m["reconciliation_error_rate"], 0.0)
        self.assertEqual(m["traceability"], 100.0)
        self.assertEqual(m["restatement_flag_rate"], 100.0)
        self.assertEqual(m["distribution_reconciled_rate"], 100.0)

    def test_sloppy_is_worse(self):
        c, s = self.results["careful"]["overall"], self.results["sloppy"]["overall"]
        self.assertLess(s["extraction_accuracy"], c["extraction_accuracy"])
        self.assertGreater(s["hallucination_rate"], 0.0)
        self.assertGreater(s["reconciliation_error_rate"], 0.0)
        self.assertEqual(s["traceability"], 0.0)
        self.assertEqual(s["restatement_flag_rate"], 0.0)
        self.assertEqual(s["distribution_reconciled_rate"], 0.0)

    def test_per_institution_present(self):
        for agent in ("careful", "sloppy"):
            self.assertEqual(len(self.results[agent]["institutions"]), 3)

    def test_deterministic(self):
        again = build_results(load_dataset())
        for agent in ("careful", "sloppy"):
            self.assertEqual(self.results[agent]["overall"], again[agent]["overall"])


class Reporting(unittest.TestCase):
    def test_table_and_markdown(self):
        results = build_results(DS)
        table = render_table(results)
        self.assertIn("OVERALL", table)
        self.assertIn("careful", table)
        self.assertIn("sloppy", table)
        md = render_markdown(results, DS)
        self.assertIn("SYNTHETIC", md)
        self.assertIn("Traceability", md)
        self.assertIn("hosp_03", md)

    def test_write_report(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.md"
            text = write_report(p)
            self.assertEqual(p.read_text(encoding="utf-8"), text)
            self.assertTrue(text.startswith("# Finpilot"))


if __name__ == "__main__":
    unittest.main()
