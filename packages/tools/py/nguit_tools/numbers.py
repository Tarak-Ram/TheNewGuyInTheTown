"""Spoken and written English amounts -> integers. Used to double-check numbers in speech.

Handles "12000", "12,000", "12k", "1.5 lakh", "twelve thousand", "fifteen hundred",
"twelve thousand five hundred". It is deliberately small: anything it cannot read is ignored.
"""

import re

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000}
_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES)

_DIGITS = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l)?(?![\w])", re.I)
_TOKEN = re.compile(r"[a-z]+|\d[\d,]*(?:\.\d+)?", re.I)


def _digit_amounts(text: str) -> list[tuple[int, int, int]]:
    out = []
    for m in _DIGITS.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        if suffix == "k" or suffix == "thousand":
            value *= 1_000
        elif suffix.startswith(("l",)) and suffix != "":
            value *= 100_000
        out.append((int(round(value)), m.start(), m.end()))
    return out


def _word_amounts(text: str) -> list[tuple[int, int, int]]:
    """Runs of number words such as "twelve thousand five hundred"."""
    out = []
    tokens = [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    i = 0
    while i < len(tokens):
        word = tokens[i][0]
        if word not in _WORDS:
            i += 1
            continue
        total = current = 0
        start, end = tokens[i][1], tokens[i][2]
        j = i
        while j < len(tokens):
            w = tokens[j][0]
            if w == "and" and j + 1 < len(tokens) and tokens[j + 1][0] in _WORDS:
                j += 1
                continue
            if w in _UNITS:
                current += _UNITS[w]
            elif w in _TENS:
                current += _TENS[w]
            elif w == "hundred":
                current = (current or 1) * 100
            elif w in _SCALES:
                total += (current or 1) * _SCALES[w]
                current = 0
            else:
                break
            end = tokens[j][2]
            j += 1
        out.append((total + current, start, end))
        i = max(j, i + 1)
    return out


def find_amounts(text: str) -> list[tuple[int, int, int]]:
    """Every (value, start, end) found, from digits and from words, in text order."""
    digits = _digit_amounts(text)
    # A word like "lakh" inside "1.5 lakh" is already counted by the digit reading.
    words = [w for w in _word_amounts(text) if not any(w[1] < d[2] and d[1] < w[2] for d in digits)]
    return sorted(digits + words, key=lambda t: t[1])


def parse_amounts(text: str) -> set[int]:
    return {value for value, _, _ in find_amounts(text)}


def normalize_numbers(text: str) -> str:
    """Rewrites spoken amounts as digits, so simple patterns can read them."""
    found = find_amounts(text)
    out, last = [], 0
    for value, start, end in found:
        if start < last:
            continue
        out.append(text[last:start])
        out.append(str(value))
        last = end
    out.append(text[last:])
    return "".join(out)
