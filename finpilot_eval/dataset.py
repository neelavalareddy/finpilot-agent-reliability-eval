"""Dataset loading. All data under data/ is SYNTHETIC and fictional."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CURRENCY_FIELDS = ("nav", "contributions", "distributions", "mgmt_fee_net")
PERCENT_FIELDS = ("net_return_pct",)
NUM_FIELDS = CURRENCY_FIELDS + PERCENT_FIELDS
ID_FIELDS = ("fund_id", "fund_name")

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text):
    """All numeric literals in text, as floats rounded to 2 dp (commas stripped)."""
    return {round(float(m.replace(",", "")), 2) for m in _NUM_RE.findall(text)}


@dataclass
class Dataset:
    truth: dict       # doc_id -> planted ground truth (ordered)
    documents: dict   # doc_id -> document text
    ledger: dict      # doc_id -> {"contributions", "distributions"}

    @property
    def registry(self):
        """Fund master list (fund_id, fund_name) in document order."""
        return [{"fund_id": t["fund_id"], "fund_name": t["fund_name"]} for t in self.truth.values()]

    @property
    def institutions(self):
        seen = []
        for t in self.truth.values():
            if t["institution"] not in seen:
                seen.append(t["institution"])
        return seen

    def all_numbers(self):
        out = set()
        for text in self.documents.values():
            out |= numbers_in(text)
        return out


def load_dataset(data_dir=None):
    d = Path(data_dir) if data_dir else DATA_DIR
    truth = json.loads((d / "ground_truth.json").read_text(encoding="utf-8"))["documents"]
    ledger = json.loads((d / "ledger.json").read_text(encoding="utf-8"))["entries"]
    documents = {k: (d / "documents" / (k + ".txt")).read_text(encoding="utf-8") for k in truth}
    return Dataset(truth=truth, documents=documents, ledger=ledger)
