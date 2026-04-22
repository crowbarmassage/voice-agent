"""Pattern-based entity extraction using regex.

Extracts well-structured data from counterparty utterances:
    - Claim status (paid, denied, pending, in process, etc.)
    - Reference/call ID numbers
    - Dates (expected payment, effective, term)
    - Dollar amounts
    - Phone/fax numbers
    - CARC/RARC denial codes
    - Rep name

Pattern extraction is fast, deterministic, and high-confidence.
It runs on every counterparty utterance. LLM extraction supplements
it for entities that don't match rigid patterns.

See docs/TIER1_FEATURES.md §C5.
"""
from __future__ import annotations

import re
from datetime import datetime

from voice_agent.extraction import ExtractedEntity, ExtractionResult

# ── Claim status patterns ──

_STATUS_PATTERNS: list[tuple[str, str]] = [
    (r"\b(paid|payment\s+issued|check\s+issued|eft\s+sent)\b", "paid"),
    (r"\b(denied|denial|rejected)\b", "denied"),
    (r"\b(pending|in\s+process|processing|under\s+review|being\s+processed)\b", "pending"),
    (r"\b(on\s+hold|suspended|pended)\b", "on_hold"),
    (r"\b(adjusted|adjustment)\b", "adjusted"),
    (r"\b(closed|finalized|resolved)\b", "closed"),
    (r"\b(received|acknowledged)\b", "received"),
]

# ── Reference number patterns ──
# Formats: AB4472, REF-12345, call ref 98765, reference number ABC123
_REFERENCE_PATTERNS = [
    r"reference\s+(?:number|#|num)?\s*(?:is\s+)?([A-Z0-9][A-Z0-9\s-]{2,15})",
    r"(?:call\s+)?ref(?:erence)?\s*(?:#|number)?\s*:?\s*([A-Z0-9][A-Z0-9\s-]{2,15})",
    r"(?:alpha|bravo|charlie|delta|echo|foxtrot)\s+(?:alpha|bravo|charlie|delta|echo|foxtrot|[a-z]+\s+)*(\d[\d\s]{2,10})",
]

# ── NATO phonetic alphabet mapping ──
_NATO_MAP = {
    "alpha": "A", "bravo": "B", "charlie": "C", "delta": "D",
    "echo": "E", "foxtrot": "F", "golf": "G", "hotel": "H",
    "india": "I", "juliet": "J", "kilo": "K", "lima": "L",
    "mike": "M", "november": "N", "oscar": "O", "papa": "P",
    "quebec": "Q", "romeo": "R", "sierra": "S", "tango": "T",
    "uniform": "U", "victor": "V", "whiskey": "W", "x-ray": "X",
    "xray": "X", "yankee": "Y", "zulu": "Z",
}

# ── Date patterns ──
_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}

_DATE_PATTERNS = [
    # "May fifteenth" / "May 15" / "May 15th"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?",
    # "05/15/2026" or "5-15-2026"
    r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
]

# Written-out ordinals
_ORDINAL_MAP = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
    "eleventh": "11", "twelfth": "12", "thirteenth": "13", "fourteenth": "14",
    "fifteenth": "15", "sixteenth": "16", "seventeenth": "17", "eighteenth": "18",
    "nineteenth": "19", "twentieth": "20", "twenty-first": "21", "twenty first": "21",
    "twenty-second": "22", "twenty second": "22", "twenty-third": "23",
    "twenty third": "23", "twenty-fourth": "24", "twenty fourth": "24",
    "twenty-fifth": "25", "twenty fifth": "25", "twenty-sixth": "26",
    "twenty sixth": "26", "twenty-seventh": "27", "twenty seventh": "27",
    "twenty-eighth": "28", "twenty eighth": "28", "twenty-ninth": "29",
    "twenty ninth": "29", "thirtieth": "30", "thirty-first": "31",
    "thirty first": "31",
}

# ── Dollar amount patterns ──
_DOLLAR_PATTERNS = [
    r"\$\s*([\d,]+(?:\.\d{2})?)",
    r"([\d,]+(?:\.\d{2})?)\s*dollars",
]

# ── Phone/fax patterns ──
_PHONE_PATTERNS = [
    r"(?:fax|phone|number)\s*(?:is|:)?\s*(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})",
    r"(\d{3}[\s.-]\d{3}[\s.-]\d{4})",
]

# ── CARC/RARC codes ──
_DENIAL_CODE_PATTERNS = [
    r"\b(CO[-\s]?\d{1,3})\b",  # CO-45, CO 16
    r"\b(PR[-\s]?\d{1,3})\b",  # PR-1
    r"\b(OA[-\s]?\d{1,3})\b",  # OA-23
    r"\b(PI[-\s]?\d{1,3})\b",  # PI-11
    r"\b(?:CARC|carc)\s*(\d{1,3})\b",
    r"\b(?:RARC|rarc)\s*(N\d{1,3}|M\d{1,3}|MA\d{1,3})\b",
    r"\breason\s+code\s+(\w{1,2}[-\s]?\d{1,3})\b",
]

# ── Check/EFT number ──
_CHECK_PATTERNS = [
    r"(?:check|eft|payment)\s*(?:number|#|num)?\s*(?:is\s+)?(\d{4,12})",
]


def extract_from_text(text: str, stt_confidence: float = 0.85) -> ExtractionResult:
    """Run all pattern extractors on a text. Returns ExtractionResult."""
    result = ExtractionResult(raw_text=text)
    text_lower = text.lower()

    # Claim status
    for pattern, status in _STATUS_PATTERNS:
        if re.search(pattern, text_lower):
            result.entities.append(ExtractedEntity(
                name="claim_status",
                value=status,
                confidence=0.9 * stt_confidence,
                source="pattern",
                source_utterance=text,
            ))
            break

    # Reference numbers (including NATO phonetic)
    ref = _extract_reference(text, text_lower, stt_confidence)
    if ref:
        result.entities.append(ref)

    # Dates
    dates = _extract_dates(text_lower, stt_confidence)
    for d in dates:
        result.entities.append(d)

    # Dollar amounts
    for pattern in _DOLLAR_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            amount = m.group(1).replace(",", "")
            result.entities.append(ExtractedEntity(
                name="dollar_amount",
                value=amount,
                confidence=0.9 * stt_confidence,
                source="pattern",
                source_utterance=text,
            ))
            break

    # Phone/fax
    for pattern in _PHONE_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            number = re.sub(r"[^\d]", "", m.group(1))
            if len(number) == 10:
                result.entities.append(ExtractedEntity(
                    name="phone_or_fax",
                    value=number,
                    confidence=0.85 * stt_confidence,
                    source="pattern",
                    source_utterance=text,
                ))
                break

    # CARC/RARC denial codes
    for pattern in _DENIAL_CODE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result.entities.append(ExtractedEntity(
                name="denial_code",
                value=m.group(1).upper().replace(" ", "-"),
                confidence=0.9 * stt_confidence,
                source="pattern",
                source_utterance=text,
            ))
            break

    # Check/EFT number
    for pattern in _CHECK_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            result.entities.append(ExtractedEntity(
                name="check_or_eft_number",
                value=m.group(1),
                confidence=0.85 * stt_confidence,
                source="pattern",
                source_utterance=text,
            ))
            break

    # Rep name — "this is [Name]" or "my name is [Name]"
    name_match = re.search(
        r"(?:this is|my name is|i'm|i am)\s+([A-Z][a-z]+)(?:\s|,|\.|$)",
        text,
        re.IGNORECASE,
    )
    if name_match:
        result.entities.append(ExtractedEntity(
            name="rep_name",
            value=name_match.group(1),
            confidence=0.8 * stt_confidence,
            source="pattern",
            source_utterance=text,
        ))

    return result


def _extract_reference(text: str, text_lower: str, stt_confidence: float) -> ExtractedEntity | None:
    """Extract reference numbers, including NATO phonetic spelling."""
    # Try NATO phonetic first: "Alpha Bravo four four seven two"
    nato_words = []
    digits = []
    words = text_lower.split()
    in_ref = False
    for word in words:
        clean = word.strip(".,;:")
        if clean in _NATO_MAP:
            nato_words.append(_NATO_MAP[clean])
            in_ref = True
        elif in_ref and clean.isdigit():
            digits.append(clean)
        elif in_ref and clean in ("zero", "one", "two", "three", "four",
                                    "five", "six", "seven", "eight", "nine"):
            digit_map = {"zero": "0", "one": "1", "two": "2", "three": "3",
                         "four": "4", "five": "5", "six": "6", "seven": "7",
                         "eight": "8", "nine": "9"}
            digits.append(digit_map[clean])
        elif in_ref:
            break

    if nato_words or (in_ref and digits):
        ref_value = "".join(nato_words) + "".join(digits)
        if len(ref_value) >= 3:
            return ExtractedEntity(
                name="reference_number",
                value=ref_value,
                confidence=0.85 * stt_confidence,
                source="pattern",
                source_utterance=text,
            )

    # Try regex patterns
    for pattern in _REFERENCE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            ref = m.group(1).strip().upper()
            if len(ref) >= 3:
                return ExtractedEntity(
                    name="reference_number",
                    value=ref,
                    confidence=0.85 * stt_confidence,
                    source="pattern",
                    source_utterance=text,
                )

    return None


def _extract_dates(text_lower: str, stt_confidence: float) -> list[ExtractedEntity]:
    """Extract dates from text."""
    entities = []
    current_year = datetime.now().year

    # "May fifteenth" / "May 15th" / "May 15, 2026"
    for month_name, month_num in _MONTH_MAP.items():
        if month_name not in text_lower:
            continue

        # Try ordinal words: "may fifteenth"
        for ordinal, day in _ORDINAL_MAP.items():
            pattern = rf"{month_name}\s+{ordinal}"
            if re.search(pattern, text_lower):
                year = current_year
                # Check for year after
                year_match = re.search(
                    rf"{month_name}\s+{ordinal}\s*,?\s*(\d{{4}})", text_lower
                )
                if year_match:
                    year = int(year_match.group(1))
                entities.append(ExtractedEntity(
                    name="date",
                    value=f"{year}-{month_num}-{day.zfill(2)}",
                    confidence=0.85 * stt_confidence,
                    source="pattern",
                    source_utterance=text_lower,
                ))
                break

        # Try numeric: "may 15" / "may 15th"
        num_match = re.search(
            rf"{month_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?",
            text_lower,
        )
        if num_match and not entities:
            day = num_match.group(1)
            year = int(num_match.group(2)) if num_match.group(2) else current_year
            entities.append(ExtractedEntity(
                name="date",
                value=f"{year}-{month_num}-{day.zfill(2)}",
                confidence=0.85 * stt_confidence,
                source="pattern",
                source_utterance=text_lower,
            ))

    # Numeric dates: 05/15/2026
    for pattern in [r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})"]:
        for m in re.finditer(pattern, text_lower):
            month, day, year = m.group(1), m.group(2), m.group(3)
            entities.append(ExtractedEntity(
                name="date",
                value=f"{year}-{month.zfill(2)}-{day.zfill(2)}",
                confidence=0.9 * stt_confidence,
                source="pattern",
                source_utterance=text_lower,
            ))

    return entities
