"""Deterministic ICAO Doc 9303 TD3 (passport) MRZ parser and builder. No ML involved."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

WEIGHTS = (7, 3, 1)
MRZ_CHARSET = re.compile(r"^[A-Z0-9<]+$")
LINE_LEN = 44


def char_value(c: str) -> int:
    if c == "<":
        return 0
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    raise ValueError(f"invalid MRZ character {c!r}")


def check_digit(data: str) -> str:
    return str(sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(data)) % 10)


@dataclass
class DigitCheck:
    name: str
    data: str
    expected: str  # digit printed in the MRZ
    computed: str | None
    valid: bool
    region: tuple[int, int] | None = None  # (line index, char index) of printed digit


@dataclass
class MRZResult:
    line1: str
    line2: str
    format_ok: bool
    format_errors: list[str] = field(default_factory=list)
    document_code: str = ""
    issuer: str = ""
    surname: str = ""
    given_names: str = ""
    passport_number: str = ""
    nationality: str = ""
    birth_date_raw: str = ""
    sex: str = ""
    expiry_date_raw: str = ""
    personal_number: str = ""
    birth_date: date | None = None
    expiry_date: date | None = None
    checks: list[DigitCheck] = field(default_factory=list)

    @property
    def all_checks_valid(self) -> bool:
        return all(c.valid for c in self.checks)


def parse_yymmdd(s: str, kind: str, today: date | None = None) -> date | None:
    today = today or date.today()
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
    if kind == "birth":
        year = 1900 + yy if 2000 + yy > today.year else 2000 + yy
    else:  # expiry: documents expire within ~ +/-20 years of today; use sliding window
        year = 2000 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _split_names(field_: str) -> tuple[str, str]:
    parts = field_.rstrip("<").split("<<", 1)
    surname = parts[0].replace("<", " ").strip()
    given = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""
    return surname, given


def parse_td3(line1: str, line2: str, today: date | None = None) -> MRZResult:
    """Parse and verify a two-line TD3 MRZ. Never raises on bad input; reports errors."""
    l1, l2 = line1.strip().upper(), line2.strip().upper()
    r = MRZResult(line1=l1, line2=l2, format_ok=True)
    for idx, ln in enumerate((l1, l2), start=1):
        if len(ln) != LINE_LEN:
            r.format_ok = False
            r.format_errors.append(f"Line {idx} has {len(ln)} characters; TD3 requires {LINE_LEN}.")
        elif not MRZ_CHARSET.match(ln):
            r.format_ok = False
            bad = sorted(set(c for c in ln if not re.match(r"[A-Z0-9<]", c)))
            r.format_errors.append(f"Line {idx} contains characters outside A-Z, 0-9, '<': {bad}.")
    if l1[:1] != "P":
        r.format_ok = False
        r.format_errors.append("Line 1 does not start with document code 'P' (passport).")
    if not r.format_ok and (len(l1) != LINE_LEN or len(l2) != LINE_LEN):
        return r  # cannot slice reliably

    r.document_code = l1[0:2].replace("<", "")
    r.issuer = l1[2:5].replace("<", "")
    r.surname, r.given_names = _split_names(l1[5:44])
    r.passport_number = l2[0:9].rstrip("<")
    r.nationality = l2[10:13].replace("<", "")
    r.birth_date_raw = l2[13:19]
    r.sex = l2[20]
    r.expiry_date_raw = l2[21:27]
    r.personal_number = l2[28:42].rstrip("<")
    r.birth_date = parse_yymmdd(r.birth_date_raw, "birth", today)
    r.expiry_date = parse_yymmdd(r.expiry_date_raw, "expiry", today)

    def add(name, data, digit_idx, line_idx=1):
        printed = l2[digit_idx]
        try:
            comp = check_digit(data)
        except ValueError:
            comp = None
        # personal number check digit may be '<' when personal number is empty
        valid = comp is not None and (printed == comp or (name == "personal_number" and printed == "<" and not r.personal_number))
        r.checks.append(DigitCheck(name, data, printed, comp, valid, (line_idx, digit_idx)))

    add("passport_number", l2[0:9], 9)
    add("date_of_birth", l2[13:19], 19)
    add("date_of_expiry", l2[21:27], 27)
    add("personal_number", l2[28:42], 42)
    add("composite", l2[0:10] + l2[13:20] + l2[21:43], 43)
    return r


def build_td3(surname: str, given: str, number: str, nationality: str, dob: date, sex: str,
              expiry: date, personal: str = "", issuer: str = "UTO", doc_code: str = "P") -> tuple[str, str]:
    """Build a valid TD3 MRZ (used by the synthetic generator and tests)."""
    def clean(s: str) -> str:
        return re.sub(r"[^A-Z0-9]+", "<", s.upper()).strip("<")

    names = f"{clean(surname)}<<{clean(given)}"
    line1 = (doc_code.ljust(2, "<") + issuer + names)[:44].ljust(44, "<")
    num = number.upper().ljust(9, "<")[:9]
    d = dob.strftime("%y%m%d")
    e = expiry.strftime("%y%m%d")
    p = personal.upper().ljust(14, "<")[:14]
    pcd = check_digit(p) if personal else "<"
    if personal:
        pcd = check_digit(p)
    body = num + check_digit(num) + nationality + d + check_digit(d) + sex + e + check_digit(e) + p + pcd
    composite = check_digit(body[0:10] + body[13:20] + body[21:43])
    return line1, body + composite


MRZ_CONFUSIONS = str.maketrans({"«": "<", "‹": "<", "›": "<", " ": "", "\t": ""})


def normalise_mrz_text(s: str) -> str:
    """Normalise raw OCR text of an MRZ line (case, spaces, chevrons). Does NOT guess characters."""
    return s.translate(MRZ_CONFUSIONS).upper()


_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "B": "8", "S": "5", "Z": "2", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G"})


def correct_by_field_type(l1: str, l2: str) -> tuple[str, str, list[dict]]:
    """Deterministic ICAO field-type correction of look-alike OCR confusions (O/0, I/1, ...).

    Letters in numeric positions become digits and digits in alphabetic positions become letters.
    Every change is recorded so the officer can see it. Check digits are then verified on the
    corrected text, and any digit mismatch still fails - we never 'fix' a wrong check digit.
    """
    changes: list[dict] = []

    # OCR frequently drops or adds characters inside long runs of '<' filler. Repair only that.
    if len(l1) < LINE_LEN and l1.endswith("<"):
        n = LINE_LEN - len(l1)
        l1 = l1 + "<" * n
        changes.append({"line": 1, "position": len(l1) - n, "from": "", "to": "<" * n, "expected": "filler run repaired"})
    elif len(l1) > LINE_LEN and l1.endswith("<"):
        n = len(l1) - LINE_LEN
        l1 = l1[:LINE_LEN]
        changes.append({"line": 1, "position": LINE_LEN, "from": "<" * n, "to": "", "expected": "filler run repaired"})
    if len(l2) != LINE_LEN and "<<<" in l2[26:]:
        i = l2.index("<<<", 26)
        j = i
        while j < len(l2) and l2[j] == "<":
            j += 1
        need = LINE_LEN - (len(l2) - (j - i))  # filler length required
        if 0 < need < 20 and need != (j - i):
            changes.append({"line": 2, "position": i, "from": "<" * (j - i), "to": "<" * need, "expected": "filler run repaired"})
            l2 = l2[:i] + "<" * need + l2[j:]

    def fix(line: str, idx: int, start: int, end: int, kind: str, line_no: int) -> str:
        seg = line[start:end]
        table = _TO_DIGIT if kind == "numeric" else _TO_ALPHA
        new = "".join(c.translate(table) if ((kind == "numeric" and not c.isdigit() and c != "<") or
                                          (kind == "alpha" and c.isdigit())) else c for c in seg)
        for i, (a, b) in enumerate(zip(seg, new)):
            if a != b:
                changes.append({"line": line_no, "position": start + i, "from": a, "to": b, "expected": kind})
        return line[:start] + new + line[end:]

    if len(l1) == LINE_LEN:
        l1 = fix(l1, 0, 2, 44, "alpha", 1)
    if len(l2) == LINE_LEN:
        for s_, e_, kind in ((9, 10, "numeric"), (10, 13, "alpha"), (13, 20, "numeric"), (21, 28, "numeric"),
                             (42, 44, "numeric")):
            l2 = fix(l2, 1, s_, e_, kind, 2)
    return l1, l2, changes
