# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "altair>=5",
#   "exrex",
#   "pandas",
#   "polars",
#   "pyarrow",
#   "vegafusion[embed]",
#   "vl-convert-python",
# ]
# ///
"""
BGP Communities — Coverage Heatmaps

Generates one AS × Community Value heatmap PDF per dataset:
  output_files/coverage-count-ours.pdf
  output_files/coverage-count-brivaldo.pdf
  output_files/coverage-count-liu.pdf
  output_files/coverage-count-krenc.pdf

Input files expected under input_files/ (same directory as this script):
  bgp_communities_dataset.csv         (Ours)
  communities.db            (Brivaldo — queried at runtime)
  semanticdic_total.json    (Liu — converted + expanded at runtime)
  krenc_dataset.csv         (Krenc)

Run with:
    uv run coverage_charts.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import altair as alt
import pandas as pd
import polars as pl
import exrex

alt.data_transformers.enable("vegafusion")

HERE       = Path(__file__).parent
INPUT_DIR  = HERE / "input_files"
OUTPUT_DIR = HERE / "output_files"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Paths ─────────────────────────────────────────────────────────────────────
OURS_PATH     = INPUT_DIR / "bgp_communities_dataset.csv"
BRIVALDO_PATH = INPUT_DIR / "communities.db"
LIU_JSON_PATH = INPUT_DIR / "semanticdic_total.json"
KRENC_PATH    = INPUT_DIR / "krenc_dataset.csv"


# ═════════════════════════════════════════════════════════════════════════════
# Brivaldo: communities.db → DataFrame
# ═════════════════════════════════════════════════════════════════════════════

def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return value.replace('"', "")
    return value


def load_brivaldo(db_path: Path) -> pd.DataFrame:
    """Query communities.db and return a DataFrame equivalent to brivaldo_full_new.csv."""
    print("  Querying Brivaldo database...")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        SELECT
            ROW_NUMBER() OVER() - 1 AS id,
            community.name          AS community,
            type.id                 AS type,
            community.level         AS level,
            community.comment       AS comment,
            type.id                 AS type_id,
            type.name               AS label
        FROM community
        JOIN type ON community.type = type.id;
    """)
    columns = [col[0] for col in cur.description]
    rows    = [[_sanitize(v) for v in row] for row in cur.fetchall()]
    con.close()

    df = pd.DataFrame(rows, columns=columns)
    df["community"] = df["community"].astype(str).str.strip()
    df["asn"]       = df["community"].apply(lambda r: r.split(":")[0])
    return df


# ═════════════════════════════════════════════════════════════════════════════
# Liu: JSON → flatten → regex-expand → DataFrame
# ═════════════════════════════════════════════════════════════════════════════

def flatten_liu_dict(raw_json: dict) -> list[dict]:
    records = []
    for asn, type_subtype_content in raw_json.items():
        for semantic_type, subtype_content in type_subtype_content.items():
            conforming = True
            match semantic_type:
                case "tag" | "sel_ann":
                    pass
                case "blackhole" | "pref" | "prepend":
                    subtype_content = {None: subtype_content}
                case "loc" | "IXP":
                    subtype_content = {semantic_type: subtype_content}
                    semantic_type = "tag"
                case t:
                    raise Exception(f"unexpected type {t}")

            for semantic_sub_type, content in subtype_content.items():
                if semantic_type == "tag":
                    match semantic_sub_type:
                        case "rel" | "loc" | "IXP" | "fac" | "asn":
                            pass
                        case "origin":
                            conforming = False
                        case s:
                            raise Exception(f"unexpected semantic sub type {s}")

                if isinstance(content[0][0], list):
                    assert len(content) == 1
                    content = content[0]

                for item in content:
                    if semantic_type == "blackhole":
                        item.append(None)

                    community_value_type, community_value, semantic_text = item

                    match community_value_type:
                        case "explicit":
                            community_value_numeric = str(community_value)
                            community_value_pattern = None
                        case "regular":
                            community_value_numeric = None
                            community_value_pattern = community_value
                        case t:
                            raise Exception(f"unexpected community value type: {t}")

                    if semantic_type == "tag" and semantic_sub_type == "rel":
                        match semantic_text:
                            case (
                                "provider" | "peer" | "customer"
                                | "partial customer" | "partial provider"
                            ):
                                pass
                            case (
                                "origin" | 30 | 20 | 10
                                | "customer,peer" | "2-CA,3-Montreal"
                                | "2-CA,3-Toronto" | "2-CA,3-Quebec"
                                | "non-customer"
                            ):
                                conforming = False
                            case m:
                                raise Exception(f"unexpected semantic text {m}")

                    records.append({
                        "asn": asn,
                        "value_type": community_value_type,
                        "value_explicit": community_value_numeric,
                        "value_regular": community_value_pattern,
                        "semantic_type": semantic_type,
                        "semantic_sub_type": semantic_sub_type,
                        "semantic_text": semantic_text,
                        "conforming": conforming,
                    })
    return records


def load_liu_expanded(json_path: Path) -> pd.DataFrame:
    """Convert semanticdic_total.json → flattened → regex-expanded DataFrame."""
    print("  Converting Liu JSON to DataFrame...")
    with open(json_path) as f:
        raw = json.load(f)

    records = flatten_liu_dict(raw)

    liu_schema = {
        "asn": "string",
        "value_type": "category",
        "value_explicit": "string",
        "value_regular": "string",
        "semantic_type": "category",
        "semantic_sub_type": "category",
        "semantic_text": "object",
        "conforming": "bool",
    }
    raw_df = pd.DataFrame(records).astype(liu_schema)
    # semantic_text can hold ints (e.g. 30, 20, 10 for rel tags).
    # PyArrow rejects mixed int/str object columns, so normalise to str first.
    raw_df["semantic_text"] = raw_df["semantic_text"].apply(
        lambda v: str(v) if v is not None else None
    )

    print("  Expanding Liu regexes (may take a moment)...")

    def _expand_regex(regex: str) -> list[str]:
        return list(exrex.generate(regex.strip("^$")))

    pl_df = (
        pl.from_pandas(raw_df.reset_index(drop=True))
        .with_columns(pl.lit("standard").cast(pl.Categorical).alias("type"))
        .with_row_index()
        .lazy()
    )

    expanded = (
        pl_df.with_columns(
            value_explicit=pl.when(pl.col("value_type") == "explicit")
            .then(pl.col("value_explicit").repeat_by(1))
            .when(pl.col("value_type") == "regular")
            .then(
                pl.col("value_regular").map_elements(
                    _expand_regex, return_dtype=pl.List(pl.String)
                )
            )
            .otherwise(None),
            value_type=pl.lit("explicit"),
        )
        .explode("value_explicit")
        .collect(engine="streaming")
        .to_pandas()
    )

    expanded["community"] = (
        expanded["asn"].astype(str) + ":" + expanded["value_explicit"].astype(str)
    )
    expanded["label"] = expanded["semantic_type"].astype(str)
    return expanded


# ═════════════════════════════════════════════════════════════════════════════
# Load all datasets
# ═════════════════════════════════════════════════════════════════════════════
print("Loading datasets...")

ours_df = pd.read_csv(OURS_PATH)
ours_df["community"] = ours_df["community"].astype(str).str.strip()
ours_df["asn"]       = ours_df["asn"].astype(str)
ours_df["label"]     = ours_df["semantic_tag"]

brivaldo_df = load_brivaldo(BRIVALDO_PATH)

krenc_df = pd.read_csv(KRENC_PATH)
krenc_df["community"] = krenc_df["community"].astype(str).str.strip()
krenc_df["label"]     = krenc_df["tag"].astype(str).str.strip()
krenc_df["asn"]       = krenc_df["community"].apply(lambda r: r.split(":")[0])

liu_df = load_liu_expanded(LIU_JSON_PATH)


# ═════════════════════════════════════════════════════════════════════════════
# Helper: parse community string into numeric (asn, value) columns
# ═════════════════════════════════════════════════════════════════════════════

def parse_community(src_df: pd.DataFrame, source_label: str) -> pd.DataFrame:
    _df = src_df.copy()
    if "community_value" not in _df.columns:
        _split = _df["community"].str.split(":", expand=True)
        _df["community_asn"]   = pd.to_numeric(_split[0], errors="coerce")
        _df["community_value"] = pd.to_numeric(_split[1], errors="coerce")
    _df["source"] = source_label
    return _df[["asn", "community_asn", "community_value", "source", "label"]].dropna()


DATASETS = {
    "Ours":     ours_df,
    "Brivaldo": brivaldo_df,
    "Liu":      liu_df,
    "Krenc":    krenc_df,
}

# ═════════════════════════════════════════════════════════════════════════════
# Coverage Heatmaps — one PDF per dataset
# ═════════════════════════════════════════════════════════════════════════════
print("Generating coverage heatmaps...")

_bin_x     = alt.Bin(maxbins=400, extent=[0, 65535])
_bin_y     = alt.Bin(maxbins=400, extent=[0, 65535])
_axis_opts = alt.Axis(ticks=False, labels=False, domain=False, titleFontSize=22)

for ds_name, src_df in DATASETS.items():
    print(f"  Processing {ds_name}...")
    _parsed = parse_community(src_df, ds_name)

    _heatmap = (
        alt.Chart(_parsed)
        .mark_rect()
        .encode(
            x=alt.X("community_asn:Q", bin=_bin_x, axis=_axis_opts, title="AS Number"),
            y=alt.Y("community_value:Q", bin=_bin_y, axis=_axis_opts, title="Community Value"),
            color=alt.Color(
                "count():Q",
                title="# Communities",
                scale=alt.Scale(scheme="plasma", domain=[0, 3000]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("community_asn:Q",  bin=_bin_x, title="AS bin"),
                alt.Tooltip("community_value:Q", bin=_bin_y, title="Value bin"),
                alt.Tooltip("count():Q",         title="# Communities"),
            ],
        )
        .properties(
            width=400,
            height=400,
            title=f"Coverage — {ds_name}",
        )
    )

    _out = OUTPUT_DIR / f"coverage-count-{ds_name.lower()}.pdf"
    _heatmap.save(str(_out))
    print(f"  → {_out.relative_to(HERE)}")

print("\nDone. All outputs written to:", OUTPUT_DIR)
