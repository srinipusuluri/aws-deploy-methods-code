"""Level 7 - policy: size limits, DLP, per-tenant token budgets."""
import re

DLP_PATTERNS = {
    "aws_access_key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "card_number": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def _luhn(digits):
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        s, alt = s + d, not alt
    return s % 10 == 0


def dlp_findings(text):
    found = []
    for name, rx in DLP_PATTERNS.items():
        for m in rx.finditer(text):
            if name == "card_number":
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 16 and _luhn(digits)):
                    continue
            found.append(name)
            break
    return found


def evaluate(text, tenant_cfg):
    """Return (decision, reasons). decision: allow | block."""
    if len(text) > tenant_cfg.get("max_input_chars", 8000):
        return "block", ["input_too_large"]
    if tenant_cfg.get("dlp", True):
        hits = dlp_findings(text)
        if hits:
            return "block", [f"dlp:{h}" for h in hits]
    return "allow", []
