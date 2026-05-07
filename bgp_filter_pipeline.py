#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bgp_filter_pipeline.py

Combined deterministic filtering pipeline for BGP community CSVs produced by
bgp_webcrawling.py. Expected input columns (5):
    asn, asname, community, description, url

Filtering stages (in order):
    1. check_column_count        — keep only lines with exactly 5 columns
    2. check_blank_cells         — reject any line with at least one empty cell
    3. check_as_numeric          — AS column must be a plain integer string
    4. check_community_syntax    — community must match A:B or A:B:C (digits or <placeholders>)
    5. check_trusted_as          — ASN must be present in the provided trusted-AS allow-list
    6. check_asn_kind            — reject private, reserved, and documentation ASNs
    7. check_toy_asn             — reject well-known toy/example ASNs (e.g. 1, 2, 10, 100)
    8. check_description_quality — reject descriptions flagged as low-quality extractions
    9. normalize_placeholder     — rewrite <DIGIT...> placeholders to DIGIT<...>

Usage:
    python3 bgp_filter_pipeline.py <input.csv> <trusted_as.txt>

Outputs:
    <input>_filtered.csv  — lines that passed all stages
    rejected_lines.csv    — lines removed at any stage, with rejection reason appended
"""

from __future__ import annotations

import os
import re
import argparse
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMUNITY_PATTERN = re.compile(r'^[\d<>\w-]+:[\d<>\w-]+(:([\d<>\w-]+))?$')

PLACEHOLDER_RE = re.compile(r'<(\d)(.*?)>')

PRIVATE_ASN_RANGES = [
    (64512, 65534),
    (4200000000, 4294967294),
]
DOCUMENTATION_ASN_RANGES = [
    (64496, 64511),
    (65536, 65551),
]
RESERVED_ASN = 0

TOY_ASNS = {1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 100, 200, 300, 400, 500}

LOW_QUALITY_PATTERNS = [
    re.compile(p, re.I) for p in [
        r'\bdebug output\b',
        r'\bshown in\b',
        r'\btutorial\b',
        r'\blab\b',
        r'\bsample\b',
        r'\bexample\b',
        r'\billustrated\b',
    ]
]

TRUNCATED_ENDINGS = [
    " to", " for", " with", " and", " or", " by", " from", " using", " where"
]

MEANINGFUL_TOKENS = {
    "announce", "advertise", "blackhole", "prepend", "learned",
    "received", "originated", "localpref", "rpki", "irr",
}

# Human-readable labels for each rejection reason prefix
REJECTION_LABELS = {
    "wrong_column_count":      "Wrong number of columns (expected 5)",
    "blank_cell":              "One or more empty cells",
    "non_numeric_asn":         "AS number is not a plain integer",
    "invalid_community_syntax":"Community value does not match A:B or A:B:C format",
    "asn_not_in_allowlist":    "AS number not present in trusted-AS allow-list",
    "asn_kind:private":        "Private AS number (RFC 6996)",
    "asn_kind:reserved":       "Reserved AS number",
    "asn_kind:documentation":  "Documentation-only AS number (RFC 5398)",
    "asn_kind:unknown":        "Unrecognised AS number format",
    "toy_asn":                 "Well-known toy or example AS number",
    "low_quality_description": "Description flagged as low-quality or non-operational",
}


def rejection_label(reason: str) -> str:
    """Return a human-readable label for a raw rejection reason code."""
    # Try exact match first
    if reason in REJECTION_LABELS:
        return REJECTION_LABELS[reason]
    # Try prefix match (e.g. wrong_column_count:3 → wrong_column_count)
    prefix = reason.split(":")[0]
    if prefix in REJECTION_LABELS:
        detail = reason[len(prefix):]
        return REJECTION_LABELS[prefix] + (f" ({detail.lstrip(':')})" if detail else "")
    # Fallback: return the raw code
    return reason


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FilterStats:
    total_read: int = 0
    passed: int = 0
    rejected: int = 0
    normalized: int = 0

    def print_summary(self) -> None:
        print(f"\n  FILTER RESULTS:")
        print(f"  ├─ Lines read            : {self.total_read}")
        print(f"  ├─ Lines passed          : {self.passed}")
        print(f"  ├─ Lines rejected        : {self.rejected}")
        print(f"  └─ Lines normalized (§9) : {self.normalized}")


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def extract_columns(line: str) -> list[str]:
    """Split a CSV line respecting double-quoted fields."""
    columns: list[str] = []
    current = ""
    inside_quotes = False
    for char in line:
        if char == '"':
            inside_quotes = not inside_quotes
        elif char == ',' and not inside_quotes:
            columns.append(current)
            current = ""
        else:
            current += char
    columns.append(current)
    return columns


def rebuild_line(cols: list[str]) -> str:
    """Rebuild a CSV line from columns, quoting fields that contain commas."""
    parts = []
    for col in cols:
        if ',' in col or '"' in col:
            col = '"' + col.replace('"', '""') + '"'
        parts.append(col)
    return ','.join(parts)


def read_csv(path: str) -> list[str]:
    for encoding in ('utf-8', 'latin-1', 'iso-8859-1', 'cp1252'):
        try:
            with open(path, 'r', encoding=encoding) as f:
                lines = [l.rstrip('\n').rstrip('\r') for l in f if l.strip()]
            print(f"  Input file read ({len(lines)} lines, encoding: {encoding})")
            return lines
        except UnicodeDecodeError:
            continue
    print("  Could not read file with any supported encoding.")
    raise SystemExit(1)


def read_trusted_as(path: str) -> set[str]:
    for encoding in ('utf-8', 'latin-1', 'iso-8859-1', 'cp1252'):
        try:
            with open(path, 'r', encoding=encoding) as f:
                result = {l.strip() for l in f if l.strip()}
            print(f"  Trusted-AS list read ({len(result)} entries, encoding: {encoding})")
            return result
        except UnicodeDecodeError:
            continue
    print("  Could not read trusted-AS file.")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Stage 1 — column count
# ---------------------------------------------------------------------------

def check_column_count(cols: list[str]) -> str | None:
    if len(cols) != 5:
        return f"wrong_column_count:{len(cols)}"
    return None


# ---------------------------------------------------------------------------
# Stage 2 — blank cells
# ---------------------------------------------------------------------------

def check_blank_cells(cols: list[str]) -> str | None:
    names = ["asn", "asname", "community", "description", "url"]
    for i, col in enumerate(cols):
        if col.strip() == "":
            return f"blank_cell:{names[i] if i < len(names) else i}"
    return None


# ---------------------------------------------------------------------------
# Stage 3 — AS must be a plain integer
# ---------------------------------------------------------------------------

def check_as_numeric(cols: list[str]) -> str | None:
    as_val = cols[0].strip().strip('"').strip("'")
    if not re.fullmatch(r'\d+', as_val):
        return f"non_numeric_asn:{as_val[:30]}"
    return None


# ---------------------------------------------------------------------------
# Stage 4 — community syntax
# ---------------------------------------------------------------------------

def check_community_syntax(cols: list[str]) -> str | None:
    community = cols[2].strip().strip('"')
    if not COMMUNITY_PATTERN.match(community):
        return f"invalid_community_syntax:{community[:40]}"
    return None


# ---------------------------------------------------------------------------
# Stage 5 — trusted-AS allow-list
# ---------------------------------------------------------------------------

def check_trusted_as(cols: list[str], trusted: set[str]) -> str | None:
    as_val = cols[0].strip().strip('"').strip("'")
    if as_val not in trusted:
        return f"asn_not_in_allowlist:{as_val}"
    return None


# ---------------------------------------------------------------------------
# Stage 6 — AS kind
# ---------------------------------------------------------------------------

def _asn_kind(as_val: str) -> str:
    try:
        asn = int(as_val.strip())
    except ValueError:
        return "unknown"
    if asn == RESERVED_ASN:
        return "reserved"
    if asn < 0:
        return "unknown"
    for lo, hi in PRIVATE_ASN_RANGES:
        if lo <= asn <= hi:
            return "private"
    for lo, hi in DOCUMENTATION_ASN_RANGES:
        if lo <= asn <= hi:
            return "documentation"
    return "public"


def check_asn_kind(cols: list[str]) -> str | None:
    kind = _asn_kind(cols[0].strip().strip('"').strip("'"))
    if kind != "public":
        return f"asn_kind:{kind}"
    return None


# ---------------------------------------------------------------------------
# Stage 7 — toy / example ASNs
# ---------------------------------------------------------------------------

def check_toy_asn(cols: list[str]) -> str | None:
    try:
        asn = int(cols[0].strip().strip('"').strip("'"))
    except ValueError:
        return None
    if asn in TOY_ASNS:
        return "toy_asn"
    return None


# ---------------------------------------------------------------------------
# Stage 8 — low-quality description
# ---------------------------------------------------------------------------

def _looks_low_quality(description: str) -> bool:
    d = description.strip().lower()
    if not d:
        return True
    if any(p.search(d) for p in LOW_QUALITY_PATTERNS):
        return True
    if any(d.endswith(ending) for ending in TRUNCATED_ENDINGS):
        return True
    words = d.split()
    if len(words) <= 3 and not any(token in d for token in MEANINGFUL_TOKENS):
        return True
    return False


def check_description_quality(cols: list[str]) -> str | None:
    description = cols[3].strip().strip('"')
    if _looks_low_quality(description):
        return "low_quality_description"
    return None


# ---------------------------------------------------------------------------
# Stage 9 — normalize placeholders in community column
# ---------------------------------------------------------------------------

def normalize_placeholder(line: str) -> tuple[str, bool]:
    """
    In the community column (index 2), rewrite placeholders of the form
    <DIGIT...> to DIGIT<...>.

    Example:  12345:<1abc> → 12345:1<abc>

    Returns the (possibly rewritten) line and a boolean indicating whether
    any substitution was actually made.
    """
    cols = extract_columns(line)
    if len(cols) < 3:
        return line, False

    original_community = cols[2]
    new_community = PLACEHOLDER_RE.sub(r'\1<\2>', original_community)

    if new_community == original_community:
        return line, False

    cols[2] = new_community
    return rebuild_line(cols), True


# ---------------------------------------------------------------------------
# Core per-line validation
# ---------------------------------------------------------------------------

def validate_line(line: str, trusted_as: set[str]) -> str | None:
    """
    Run all filter stages in order. Returns the first rejection reason,
    or None if the line passes all stages.
    """
    cols = extract_columns(line)

    for check_fn in (
        check_column_count,
        check_blank_cells,
        check_as_numeric,
        check_community_syntax,
    ):
        reason = check_fn(cols)
        if reason:
            return reason

    reason = check_trusted_as(cols, trusted_as)
    if reason:
        return reason

    for check_fn in (
        check_asn_kind,
        check_toy_asn,
        check_description_quality,
    ):
        reason = check_fn(cols)
        if reason:
            return reason

    return None


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_pipeline(input_path: str, trusted_as_path: str) -> None:
    for path in (input_path, trusted_as_path):
        if not os.path.exists(path):
            print(f"\n  File not found: {path}")
            raise SystemExit(1)

    trusted_as = read_trusted_as(trusted_as_path)

    print(f"\n  Reading: {input_path}")
    lines = read_csv(input_path)

    stats = FilterStats(total_read=len(lines))
    valid_lines:    list[str] = []
    invalid_lines:  list[tuple[str, str]] = []   # (line, reason)

    for line in lines:
        reason = validate_line(line, trusted_as)
        if reason is None:
            # Stage 9: normalize placeholders
            normalized_line, was_changed = normalize_placeholder(line)
            if was_changed:
                stats.normalized += 1
            valid_lines.append(normalized_line)
            stats.passed += 1
        else:
            invalid_lines.append((line, reason))
            stats.add_rejection(reason)

    stats.print_summary()

    base = os.path.splitext(os.path.basename(input_path))[0]

    filtered_path = f"{base}_filtered.csv"
    with open(filtered_path, 'w', encoding='utf-8') as f:
        for line in valid_lines:
            f.write(line + "\n")
    print(f"\n  Filtered output : {filtered_path} ({len(valid_lines)} lines)")

    rejected_path = "rejected_lines.csv"
    with open(rejected_path, 'w', encoding='utf-8') as f:
        for line, reason in invalid_lines:
            label = rejection_label(reason)
            # Append the human-readable rejection reason as a 6th column
            if ',' in label or '"' in label:
                label = '"' + label.replace('"', '""') + '"'
            f.write(line + "," + label + "\n")
    print(f"  Rejected lines  : {rejected_path} ({len(invalid_lines)} lines)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combined deterministic filter pipeline for BGP community CSVs."
    )
    parser.add_argument("input_csv",  help="CSV produced by bgp_webcrawling.py")
    parser.add_argument("trusted_as", help="File with one trusted ASN per line")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args.input_csv, args.trusted_as)
