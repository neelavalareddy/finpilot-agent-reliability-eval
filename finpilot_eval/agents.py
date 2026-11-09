"""Two deterministic, rule-based reference agents (no LLM, no network).

Agent interface (what Finpilot would implement for their own agents):

    agent.name -> str
    agent.extract(doc_id, text, context) -> {
        "doc_id": str, "fund_id": str|None, "fund_name": str|None,
        "fields": {field: {"value": float|None, "source": doc_id|None}, ...},
        "flags": {"restatement_flagged": bool, "distribution_reconciled": bool},
    }
    context = {"registry": [{"fund_id", "fund_name"}...], "ledger": {"contributions", "distributions"}|None}
"""
import re

MONEY = r"\$([\d,]+(?:\.\d+)?)"
FIELDS = ("nav", "contributions", "distributions", "mgmt_fee_net", "net_return_pct")


def _num(s):
    return float(s.replace(",", ""))


def _header(text, key):
    m = re.search(r"^" + key + r":\s*(.+?)\s*$", text, re.M)
    return m.group(1) if m else None


def _money_line(pattern, text):
    m = re.search(pattern + r"\s*" + MONEY, text, re.M)
    return _num(m.group(1)) if m else None


def _percent_line(text):
    m = re.search(r"^Net Return[^:\n]*:\s*([\d.]+)%", text, re.M)
    return float(m.group(1)) if m else None


def _section(text, fund_id):
    """If the doc has '[FUND-ID] ...' sections, return the body for fund_id."""
    parts = re.split(r"(?m)^\[([A-Z0-9-]+)\][^\n]*$", text)
    if len(parts) < 3:
        return text
    for i in range(1, len(parts) - 1, 2):
        if parts[i] == fund_id:
            return parts[i + 1]
    return text


def _cash_movement(text):
    m = re.search(r"^Cash Movement:\s*" + MONEY + r"(.*)$", text, re.M)
    if not m:
        return None, ""
    return _num(m.group(1)), m.group(2).lower()


def _result(doc_id, fund_id, fund_name, values, cite, flags):
    fields = {}
    for f in FIELDS:
        v = values.get(f)
        fields[f] = {"value": v, "source": doc_id if (cite and v is not None) else None}
    return {"doc_id": doc_id, "fund_id": fund_id, "fund_name": fund_name, "fields": fields, "flags": flags}


class CarefulAgent:
    """Uses restated NAV, net fee, classifies cash flow by wording, keeps funds
    separate, reports absent fields as missing (None), cites the source doc."""
    name = "careful"

    def extract(self, doc_id, text, context=None):
        context = context or {}
        fund_id = _header(text, "Fund ID")
        fund_name = _header(text, "Fund Name")
        body = _section(text, fund_id)

        restated = _money_line(r"^NAV \(restated[^)]*\):", body)
        nav = restated if restated is not None else _money_line(r"^NAV:", body)

        contributions = _money_line(r"^Contributions:", body)
        distributions = _money_line(r"^Distributions:", body)
        if contributions is None and distributions is None:
            amount, desc = _cash_movement(body)
            if amount is not None:
                if "paid to the investor" in desc:
                    contributions, distributions = 0.0, amount
                elif "paid by the investor" in desc or "called" in desc:
                    contributions, distributions = amount, 0.0

        fee = _money_line(r"^Management Fee \(net[^)]*\):", body)
        if fee is None:
            fee = _money_line(r"^Management Fee:", body)

        values = {"nav": nav, "contributions": contributions, "distributions": distributions,
                  "mgmt_fee_net": fee, "net_return_pct": _percent_line(body)}

        ledger = context.get("ledger")
        reconciled = bool(ledger and distributions is not None
                          and abs(distributions - ledger["distributions"]) <= 1.0)
        flags = {"restatement_flagged": restated is not None, "distribution_reconciled": reconciled}
        return _result(doc_id, fund_id, fund_name, values, True, flags)


class SloppyAgent:
    """Takes the first figure seen, gross fee, calls every cash movement a
    contribution, matches funds by name prefix, invents missing values, no citations."""
    name = "sloppy"
    PREFIX = 22
    INVENTED_RETURN = 7.25
    INVENTED_FEE_RATE = 0.0125

    def extract(self, doc_id, text, context=None):
        context = context or {}
        fund_id = fund_name = None
        for entry in context.get("registry", []):
            if entry["fund_name"][: self.PREFIX] in text:
                fund_id, fund_name = entry["fund_id"], entry["fund_name"]
                break

        nav = _money_line(r"^NAV[^:\n]*:", text)
        contributions = _money_line(r"^Contributions:", text)
        distributions = _money_line(r"^Distributions:", text)
        amount, _ = _cash_movement(text)
        if amount is not None:
            contributions, distributions = amount, 0.0

        fee = _money_line(r"^Management Fee[^:\n]*:", text)
        if fee is None and nav is not None:
            fee = float(round(nav * self.INVENTED_FEE_RATE))
        ret = _percent_line(text)
        if ret is None:
            ret = self.INVENTED_RETURN

        values = {"nav": nav, "contributions": contributions, "distributions": distributions,
                  "mgmt_fee_net": fee, "net_return_pct": ret}
        flags = {"restatement_flagged": False, "distribution_reconciled": False}
        return _result(doc_id, fund_id, fund_name, values, False, flags)
