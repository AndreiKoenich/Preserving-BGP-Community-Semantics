# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "altair>=5",
#   "exrex",
#   "numpy",
#   "pandas",
#   "polars",
#   "pyarrow",
#   "scikit-learn",
#   "vegafusion[embed]",
#   "vl-convert-python",
# ]
# ///
"""
BGP Communities — Confusion Matrices

Generates two confusion matrix PDFs:

  output_files/ours_krenc_matrix.pdf   — Ours (fidelity dataset) vs. Krenc
                                         Ours labels collapsed to action/info,
                                         compared against Krenc tags.

  output_files/krenc_liu_matrix.pdf    — Krenc vs. Liu
                                         Liu semantics collapsed to action/info,
                                         compared against Krenc tags.

Input files expected under input_files/ (same directory as this script):
  our_dataset.csv       (Ours)
  communities.db          (Brivaldo — not used here, kept for consistency)
  krenc_dataset.csv       (Krenc)
  semanticdic_total.json  (Liu — converted + expanded at runtime)

Run with:
    uv run confusion_matrixes.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import polars as pl
import exrex
from sklearn.metrics import confusion_matrix

alt.data_transformers.enable("vegafusion")

HERE       = Path(__file__).parent
INPUT_DIR  = HERE / "input_files"
OUTPUT_DIR = HERE / "output_files"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Paths ─────────────────────────────────────────────────────────────────────
OURS_PATH     = INPUT_DIR / "our_dataset.csv"
KRENC_PATH    = INPUT_DIR / "krenc_dataset.csv"
LIU_JSON_PATH = INPUT_DIR / "semanticdic_total.json"


# ═════════════════════════════════════════════════════════════════════════════
# Shared: Altair confusion-matrix chart builder
# ═════════════════════════════════════════════════════════════════════════════

def build_confusion_chart(
    true_labels: pd.Series,
    pred_labels: pd.Series,
    x_title: str,
    y_title: str,
    output_path: Path,
) -> None:
    """Compute confusion matrix and save an Altair heatmap+text chart to PDF."""
    _all_labels = sorted(set(true_labels) | set(pred_labels))
    _cm = confusion_matrix(true_labels, pred_labels, labels=_all_labels)

    _cm_df = (
        pd.DataFrame(_cm, index=_all_labels, columns=_all_labels)
        .reset_index()
        .melt(id_vars="index", var_name="norm_label", value_name="count")
        .rename(columns={"index": "true_label"})
    )
    _total = _cm_df["count"].sum()
    _cm_df["percent"]      = _cm_df["count"] / _total
    _cm_df["display_text"] = _cm_df.apply(
        lambda r: f"{r['count']}\n({r['percent']:.1%})", axis=1
    )

    _base = alt.Chart(_cm_df).encode(
        x=alt.X("norm_label:N", sort=_all_labels, axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("true_label:N", sort=_all_labels[::-1]),
    )

    _rect = (
        alt.Chart(_cm_df)
        .mark_rect()
        .encode(
            x=alt.X(
                "norm_label:N",
                title=x_title,
                sort=_all_labels,
                axis=alt.Axis(labelAngle=-35, titleFontSize=18, labelFontSize=14),
            ),
            y=alt.Y(
                "true_label:N",
                title=y_title,
                sort=_all_labels[::-1],
                axis=alt.Axis(titleFontSize=18, labelFontSize=14),
            ),
            color=alt.Color(
                "count:Q",
                title="# Communities",
                scale=alt.Scale(scheme="blues", domain=[0, int(_cm.max())]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("true_label:N", title="True Label"),
                alt.Tooltip("norm_label:N", title="Predicted Label"),
                alt.Tooltip("count:Q",      title="# Communities"),
            ],
        )
        .properties(width=200, height=200)
    )

    _text = _base.mark_text(fontSize=18, fontWeight="bold", lineBreak="\n").encode(
        text=alt.Text("display_text:N"),
        color=alt.condition(
            alt.datum.count > int(_cm.max()) / 2,
            alt.value("white"),
            alt.value("black"),
        ),
    )

    (_rect + _text).save(str(output_path))
    print(f"  → {output_path.relative_to(HERE)}")


# ═════════════════════════════════════════════════════════════════════════════
# Liu: JSON → flatten → regex-expand
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


def load_liu_polars(json_path: Path) -> pl.DataFrame:
    """Convert semanticdic_total.json → flattened → Polars DataFrame (pre-expansion)."""
    print("  Converting Liu JSON...")
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
    pd_df = pd.DataFrame(records).astype(liu_schema)
    # semantic_text can hold ints (e.g. 30, 20, 10 for rel tags).
    # PyArrow rejects mixed int/str object columns, so normalise to str first.
    pd_df["semantic_text"] = pd_df["semantic_text"].apply(
        lambda v: str(v) if v is not None else None
    )

    print("  Expanding Liu regexes (may take a moment)...")

    return (
        pl.from_pandas(pd_df.reset_index(drop=True))
        .with_columns(pl.lit("standard").cast(pl.Categorical).alias("type"))
        .with_row_index()
    )


def expand_liu(df: pl.LazyFrame) -> pl.LazyFrame:
    def _expand_regex(regex: str) -> list[str]:
        return list(exrex.generate(regex.strip("^$")))

    return (
        df.with_columns(
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
    )


# ═════════════════════════════════════════════════════════════════════════════
# Polars helper: parse community type (standard / extended / large)
# ═════════════════════════════════════════════════════════════════════════════

def parse_community_type(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.with_columns(
            parts=pl.col("community")
            .str.splitn(":", 3)
            .struct.rename_fields(["first", "second", "third"]),
        )
        .unnest("parts")
        .with_columns(
            type=pl.when(pl.col("third").str.contains(":", literal=True))
            .then(None)
            .when(
                pl.col("first").is_not_null()
                & pl.col("second").is_not_null()
                & pl.col("third").is_null()
            )
            .then(pl.lit("standard"))
            .when(
                pl.col("first").str.contains("(?i)^<?(rt|target|ro|soo|origin)>?$")
                & pl.col("second").is_not_null()
                & pl.col("third").is_not_null()
            )
            .then(pl.lit("extended"))
            .when(
                pl.col("first").is_not_null()
                & pl.col("second").is_not_null()
                & pl.col("third").is_not_null()
            )
            .then(pl.lit("large"))
            .otherwise(None)
            .cast(pl.Categorical)
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# MATRIX 1 — Ours × Krenc
#
#   - Load Ours (fidelity) dataset; keep only standard:numeric communities;
#     drop communities with inconsistent labels across ASes.
#   - Inner-join with Krenc on `community`.
#   - Collapse Ours labels: information:* → "info", everything else → "action".
#   - Compare against Krenc `tag`.
# ═════════════════════════════════════════════════════════════════════════════
print("Preparing Ours × Krenc matrix...")

_first_16_bits = re.compile(r"\d+:.*")
_tag_regex     = re.compile(r"<[^>]*>")


def _valid_first_half(community: str) -> bool:
    return bool(re.search(_first_16_bits, str(community)))


ours_raw = pd.read_csv(OURS_PATH)
ours_raw["community"] = ours_raw["community"].astype(str).str.strip()
ours_raw["asn"]       = ours_raw["asn"].astype(str)
ours_raw["label"]     = ours_raw["semantic_tag"]

# Sanitize
_ours = (
    ours_raw
    .loc[lambda d: d["community"].map(_valid_first_half)]
    .dropna()
    .copy()
)
_ours["community_regex"] = _ours["community"].str.replace(_tag_regex, r"\\d+", regex=True)
_ours = _ours[
    _ours["community"].str.contains(
        r"^(?:\d+)(?::(?:\d+|\d+(<[^>]*>)*\d*|\d*(<[^>]*>)*\d+))*$"
    )
]
_ours_explicit = _ours.loc[_ours["structure_tag"] == "standard:numeric"].copy()

# Identify communities with inconsistent labels
_consistency = (
    _ours.groupby("community")["label"]
    .agg(all_same=lambda x: x.nunique() == 1)
    .reset_index()
)
_cursed = set(_consistency.loc[~_consistency["all_same"], "community"])

# Load Krenc
krenc_pd = pd.read_csv(KRENC_PATH)
krenc_pd["community"] = krenc_pd["community"].astype(str).str.strip()
krenc_pd["label"]     = krenc_pd["tag"].astype(str).str.strip()

# Merge and filter
_merged_ok = (
    _ours_explicit
    .merge(krenc_pd, on="community", how="inner")
    .loc[lambda d: ~d["community"].isin(_cursed)]
    .copy()
)

# Collapse Ours labels: information:* → info, everything else → action
_merged_ok["ours_collapsed"] = np.where(
    _merged_ok["label_x"].str.contains(r"\binformation:", regex=True),
    "info",
    "action",
)

print("Generating ours_krenc_matrix.pdf...")
build_confusion_chart(
    true_labels  = _merged_ok["ours_collapsed"],
    pred_labels  = _merged_ok["label_y"],
    y_title      = "Krenc Label",
    x_title      = "Our Label",
    output_path  = OUTPUT_DIR / "ours_krenc_matrix.pdf",
)


# ═════════════════════════════════════════════════════════════════════════════
# MATRIX 2 — Krenc × Liu
#
#   - Load Krenc with Polars; parse community type.
#   - Load + expand Liu from JSON (flatten_liu_dict → expand_liu).
#   - Join Krenc × Liu on (first=asn, second=value_explicit).
#   - Collapse Liu semantics: non-"tag" types → action=True, "tag" → action=False.
#   - expected_krenc_tag: any action in group → "action", otherwise "info".
#   - Compare expected_krenc_tag against Krenc `tag`.
# ═════════════════════════════════════════════════════════════════════════════
print("Preparing Krenc × Liu matrix...")

krenc_pl = (
    pl.read_csv(KRENC_PATH)
    .pipe(parse_community_type)
    .with_row_index()
)

liu_pl = load_liu_polars(LIU_JSON_PATH)

# Join and aggregate
krenc_liu_df = (
    krenc_pl.lazy()
    .join(
        liu_pl.lazy()
        .with_columns(
            krenc_expects_action=pl.when(pl.col("semantic_type") == "tag")
            .then(False)
            .otherwise(True)
        )
        .pipe(expand_liu),
        left_on=["first", "second"],
        right_on=["asn", "value_explicit"],
        coalesce=False,
    )
    .group_by(["index", "asn", "value_explicit"])
    .agg(
        pl.col(krenc_pl.drop("index").columns).first(),
        pl.col("krenc_expects_action").drop_nulls(),
        index_right=pl.col("index_right").unique().sort(),
        values=pl.when(pl.col("value_regular").is_not_null())
        .then(pl.col("value_regular"))
        .otherwise(pl.col("value_explicit"))
        .unique()
        .sort(),
        semantics=pl.concat_str(
            [pl.col("semantic_type"), pl.col("semantic_sub_type")],
            separator=":",
            ignore_nulls=True,
        ).unique().sort(),
        semantics_text=pl.col("semantic_text").drop_nulls().unique().sort(),
    )
    .drop("value_explicit")
    .unique(["index", "index_right"])
    .collect(engine="streaming")
)

# Derive expected tag and matched flag
krenc_liu_expected_df = (
    krenc_liu_df
    .with_columns(
        expected_krenc_tag=pl.when(pl.col("krenc_expects_action").list.any())
        .then(pl.lit("action"))
        .otherwise(pl.lit("info"))
    )
    .with_columns(matched=(pl.col("tag") == pl.col("expected_krenc_tag")))
    .to_pandas()
)

print("Generating krenc_liu_matrix.pdf...")
build_confusion_chart(
    true_labels  = krenc_liu_expected_df["expected_krenc_tag"],
    pred_labels  = krenc_liu_expected_df["tag"],
    y_title      = "Krenc Label",
    x_title      = "Liu Label",
    output_path  = OUTPUT_DIR / "krenc_liu_matrix.pdf",
)

print("\nDone. All outputs written to:", OUTPUT_DIR)
