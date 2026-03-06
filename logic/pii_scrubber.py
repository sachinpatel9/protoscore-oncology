"""
PII scrubber for ProtoScore V2.

Redacts personally identifiable information from protocol text before
sending to external LLM APIs. While clinical protocols typically don't
contain patient data, this layer provides defense-in-depth.
"""

import re
from dataclasses import dataclass


@dataclass
class RedactionRecord:
    """Record of a single PII redaction."""
    original: str
    redacted: str
    pii_type: str
    start: int
    end: int


# --- PII Detection Patterns ---

# US Social Security Numbers
SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

# Phone numbers (US formats)
PHONE_PATTERN = re.compile(
    r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
)

# Email addresses
EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)

# Medical Record Numbers (common patterns: MRN-XXXXXX, MR# XXXXXX)
MRN_PATTERN = re.compile(
    r'\b(?:MRN|MR#|Medical Record)\s*[-:#]?\s*\d{4,10}\b',
    re.IGNORECASE,
)

# Date of birth patterns (MM/DD/YYYY, YYYY-MM-DD near "DOB" or "birth")
DOB_PATTERN = re.compile(
    r'(?:DOB|date of birth|born)\s*[:;]?\s*'
    r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})',
    re.IGNORECASE,
)

# Patient/subject identifiers near name-like patterns
PATIENT_ID_PATTERN = re.compile(
    r'(?:patient|subject|participant)\s*(?:name|id|identifier)\s*[:;]?\s*'
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}|\d{4,})',
    re.IGNORECASE,
)

PII_PATTERNS = [
    (SSN_PATTERN, "SSN", "[SSN_REDACTED]"),
    (PHONE_PATTERN, "phone", "[PHONE_REDACTED]"),
    (EMAIL_PATTERN, "email", "[EMAIL_REDACTED]"),
    (MRN_PATTERN, "mrn", "[MRN_REDACTED]"),
    (DOB_PATTERN, "dob", "[DOB_REDACTED]"),
    (PATIENT_ID_PATTERN, "patient_id", "[PATIENT_ID_REDACTED]"),
]


def scrub_pii(text: str) -> tuple[str, list[RedactionRecord]]:
    """
    Scan text for PII patterns and redact them.

    Args:
        text: Input text to scrub

    Returns:
        Tuple of (scrubbed_text, list of RedactionRecords)
    """
    redactions: list[RedactionRecord] = []
    scrubbed = text

    for pattern, pii_type, replacement in PII_PATTERNS:
        for match in pattern.finditer(scrubbed):
            redactions.append(RedactionRecord(
                original=match.group(),
                redacted=replacement,
                pii_type=pii_type,
                start=match.start(),
                end=match.end(),
            ))

        scrubbed = pattern.sub(replacement, scrubbed)

    return scrubbed, redactions


def scrub_document_chunks(chunks: list[str]) -> tuple[list[str], list[RedactionRecord]]:
    """
    Scrub PII from a list of text chunks (e.g., page texts).

    Args:
        chunks: List of text strings to scrub

    Returns:
        Tuple of (scrubbed_chunks, all_redactions)
    """
    all_redactions: list[RedactionRecord] = []
    scrubbed_chunks = []

    for chunk in chunks:
        scrubbed, redactions = scrub_pii(chunk)
        scrubbed_chunks.append(scrubbed)
        all_redactions.extend(redactions)

    return scrubbed_chunks, all_redactions
