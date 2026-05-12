# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas",
#   "polars",
#   "pyarrow",
#   "altair>=5",
#   "vegafusion",
#   "vl-convert-python",
# ]
# ///

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Callable

import altair as alt
import polars as pl


def _step(msg: str) -> float:
    print(f"[{time.strftime('%H:%M:%S')}] {msg} ...", flush=True)
    return time.perf_counter()


def _done(t0: float) -> None:
    print(f"  done ({time.perf_counter() - t0:.1f}s)", flush=True)


# ---------------------------------------------------------------------------
# Constants — well-known BGP communities (IANA)
# ---------------------------------------------------------------------------
well_known_communities = {
    "PLANNED_SHUT":                "65535:0",
    "ACCEPT_OWN":                  "65535:1",
    "ROUTE_FILTER_TRANSLATED_V4":  "65535:2",
    "ROUTE_FILTER_V4":             "65535:3",
    "ROUTE_FILTER_TRANSLATED_V6":  "65535:4",
    "ROUTE_FILTER_V6":             "65535:5",
    "LLGR_STALE":                  "65535:6",
    "NO_LLGR":                     "65535:7",
    "ACCEPT_OWN_NEXTHOP":          "65535:8",
    "BLACKHOLE":                   "65535:666",
    "NO_EXPORT":                   "65535:65281",
    "NO_ADVERTISE":                "65535:65282",
    "NO_EXPORT_SUBCONFED":         "65535:65283",
    "NO_PEER":                     "65535:65284",
}
communities_well_known = {v: k for k, v in well_known_communities.items()}

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_files")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_asn_category(col: pl.Expr) -> pl.Expr:
    """Map an integer ASN column to its IANA category string."""
    return (
        pl.when(col == 0)
        .then(pl.lit("reserved"))
        .when(col == 23456)
        .then(pl.lit("AS_TRANS"))
        .when(col.is_between(64496, 64511))
        .then(pl.lit("documentation"))
        .when(col.is_between(64512, 65534))
        .then(pl.lit("private"))
        .when(col == 65535)
        .then(pl.lit("reserved"))
        .when(col.is_between(65536, 65551))
        .then(pl.lit("documentation"))
        .when(col.is_between(65552, 131071))
        .then(pl.lit("reserved"))
        .when(col.is_between(155962, 196607))
        .then(pl.lit("unallocated"))
        .when(col.is_between(216476, 262143))
        .then(pl.lit("unallocated"))
        .when(col.is_between(275869, 327679))
        .then(pl.lit("unallocated"))
        .when(col.is_between(329728, 393215))
        .then(pl.lit("unallocated"))
        .when(col.is_between(402333, 4199999999))
        .then(pl.lit("unallocated"))
        .when(col.is_between(4200000000, 4294967294))
        .then(pl.lit("private"))
        .when(col == 4294967295)
        .then(pl.lit("reserved"))
        .otherwise(pl.lit("assignable"))
        .cast(pl.Categorical)
    )


def parse_community_type(df: pl.DataFrame) -> pl.DataFrame:
    """Split `community` into first/second/third parts and classify its type."""
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


def join_liu_routeviews(
    liu_df: pl.LazyFrame, routeviews_df: pl.LazyFrame
) -> pl.LazyFrame:
    return liu_df.join(
        routeviews_df,
        left_on=["asn", "type"],
        right_on=["first", "type"],
        how="inner",
    ).filter(
        pl.when(pl.col("value_type") == "explicit")
        .then(pl.col("second") == pl.col("value_explicit"))
        .when(pl.col("value_type") == "regular")
        .then(pl.col("second").str.contains(pl.col("value_regular")))
        .otherwise(False)
    )


def join_ours_routeviews(
    ours_df: pl.LazyFrame, routeviews_df: pl.LazyFrame
) -> pl.LazyFrame:
    ours_df = ours_df.with_columns(
        community_regex=(
            "^" + pl.col("community").str.replace_all("<[^>]*>", r"\d+") + "$"
        ),
    )
    community_match = pl.col("community_right").str.contains(
        pl.col("community_regex")
    )
    return pl.concat(
        [
            ours_df.join(routeviews_df, on=["first", "type"]),
            ours_df.join(routeviews_df, on=["second", "type"]),
            ours_df.join(routeviews_df, on=["third", "type"]),
        ]
    ).filter(community_match)


def match_communities(
    left_df: pl.DataFrame,
    right_df: pl.DataFrame,
    how: Callable[[pl.LazyFrame, pl.LazyFrame], pl.LazyFrame],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join two datasets and annotate each side with a `matched` boolean."""
    left_lf  = left_df.lazy().with_row_index("left_id")
    right_lf = right_df.lazy().with_row_index("right_id")

    joined = how(left_lf, right_lf)

    matched_left_ids  = joined.select("left_id").unique().with_columns(matched=pl.lit(True))
    matched_right_ids = joined.select("right_id").unique().with_columns(matched=pl.lit(True))

    left_lf = (
        left_lf.join(matched_left_ids, on="left_id", how="left")
        .with_columns(pl.col("matched").fill_null(False))
        .drop("left_id")
    )
    right_lf = (
        right_lf.join(matched_right_ids, on="right_id", how="left")
        .with_columns(pl.col("matched").fill_null(False))
        .drop("right_id")
    )
    return pl.collect_all([left_lf, right_lf])


def _enrich_with_asn_category(df: pl.DataFrame) -> pl.DataFrame:
    """Add asn_from_community, its IANA category, and iana_well_known columns."""
    return (
        df.with_columns(
            asn_from_community=pl.when(pl.col("type") == "extended")
            .then(pl.col("second"))
            .when(pl.col("type").is_in(["standard", "large"]))
            .then(pl.col("first"))
            .otherwise(None)
        )
        .with_columns(
            asn_from_community_int=pl.col("asn_from_community").cast(pl.UInt64, strict=False)
        )
        .with_columns(asn_from_community_cat=get_asn_category(pl.col("asn_from_community_int")))
        .drop("asn_from_community_int")
        .with_columns(
            iana_well_known=pl.col("community").replace_strict(
                communities_well_known, default=None
            )
        )
    )


def _load_brivaldo_from_db(db_path: str) -> pl.DataFrame:
    """Read communities.db and return a DataFrame equivalent to brivaldo_full_new.csv."""
    def sanitize(value):
        if isinstance(value, str):
            return value.replace('"', "")
        return value

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
        JOIN type ON community.type = type.id
    """)
    columns = [col[0] for col in cur.description]
    rows    = [[sanitize(v) for v in row] for row in cur.fetchall()]
    con.close()
    return pl.DataFrame({col: [row[i] for row in rows] for i, col in enumerate(columns)})


def _flatten_liu_dict(liu_json: dict) -> list[dict]:
    """Flatten the nested Liu JSON structure into a list of records."""
    records = []

    for asn, type_subtype_content in liu_json.items():
        for semantic_type, subtype_content in type_subtype_content.items():
            conforming = True

            match semantic_type:
                case "tag" | "sel_ann":
                    pass
                case "blackhole" | "pref" | "prepend":
                    subtype_content = {None: subtype_content}
                case "loc" | "IXP":
                    conforming = True
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
                    conforming = True
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
                        "asn":              asn,
                        "value_type":       community_value_type,
                        "value_explicit":   community_value_numeric,
                        "value_regular":    community_value_pattern,
                        "semantic_type":    semantic_type,
                        "semantic_sub_type":semantic_sub_type,
                        "semantic_text":    str(semantic_text) if semantic_text is not None else None,
                        "conforming":       conforming,
                    })

    return records


def _load_liu_from_json(json_path: str) -> pl.DataFrame:
    """Read semanticdic_total.json and return the liu DataFrame."""
    import pandas as pd

    t = _step("  reading JSON file")
    with open(json_path) as f:
        liu_json = json.load(f)
    _done(t)

    t = _step("  flattening Liu dict")
    records = _flatten_liu_dict(liu_json)
    print(f"  {len(records):,} records extracted", flush=True)
    _done(t)

    t = _step("  building pandas DataFrame")
    liu_schema = {
        "asn":              "string",
        "value_type":       "category",
        "value_explicit":   "string",
        "value_regular":    "string",
        "semantic_type":    "category",
        "semantic_sub_type":"category",
        "semantic_text":    "object",
        "conforming":       "bool",
    }
    pd_df = pd.DataFrame(records).astype(liu_schema)
    pd_df["semantic_text"] = pd_df["semantic_text"].apply(
        lambda v: str(v) if v is not None else None
    )
    _done(t)

    t = _step("  converting pandas → polars")
    result = pl.from_pandas(pd_df.reset_index(drop=True)).with_columns([
        pl.col("asn").cast(pl.String),
        pl.col("value_type").cast(pl.Categorical),
        pl.col("value_explicit").cast(pl.String),
        pl.col("value_regular").cast(pl.String),
        pl.col("semantic_type").cast(pl.Categorical),
        pl.col("semantic_sub_type").cast(pl.Categorical),
        pl.col("semantic_text").cast(pl.String),
        pl.col("conforming").cast(pl.Boolean),
    ])
    _done(t)
    return result


# ---------------------------------------------------------------------------
# Load RIPE ASN list
# ---------------------------------------------------------------------------
t0 = _step("Loading RIPE ASN list")
ripe_asn_df = (
    pl.read_lines("input_files/ripe-asn-replication.list")
    .with_columns(
        line=pl.when(pl.col("line") == "23456 AS_TRANS; reserved by RFC6793")
        .then(pl.col("line") + ", ZZ")
        .otherwise(pl.col("line")),
    )
    .with_columns(parsed_entry=pl.col("line").str.extract_groups(
        r"^(?P<asn>\d+) (?P<as_name_long>.*), (?P<asn_ripe_location>\w+)$"
    ))
    .drop("line")
    .unnest("parsed_entry")
    .with_columns(pl.col(pl.String).str.strip_chars())
    .with_columns(
        as_name=pl.col("as_name_long").str.extract(r"^(?P<as_name>[0-9A-Z_\-]+( |$))"),
        asn_ripe_location=pl.col("asn_ripe_location")
        .replace("ZZ", None)
        .cast(pl.Categorical),
    )
    .unique("asn", keep="first")
)
print(f"  {len(ripe_asn_df):,} ASNs loaded", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Load our dataset (passo5)
# ---------------------------------------------------------------------------
t0 = _step("Loading our dataset (bgp_communities_dataset.csv)")
passo5_raw_df = pl.read_csv(
    "input_files/bgp_communities_dataset.csv",
    has_header=True,
    schema={
        "asn":               pl.String,
        "as_name":           pl.String,
        "community":         pl.String,
        "description":       pl.String,
        "url":               pl.String,
        "structure_tag":     pl.String,
        "model_confidence":  pl.String,
        "semantic_tag":      pl.String,
        "qualifiers":        pl.String,
        "semantic_notes":    pl.String,
        "confidence_explain":pl.String,
    },
).pipe(parse_community_type)
print(f"  {len(passo5_raw_df):,} rows loaded", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Load Liu dataset
# ---------------------------------------------------------------------------
t0 = _step("Loading Liu dataset (semanticdic_total.json)")
liu_df = (
    _load_liu_from_json("input_files/semanticdic_total.json")
    .with_columns(type=pl.lit("standard").cast(pl.Categorical))
    .with_columns(asn_int=pl.col("asn").cast(pl.UInt64, strict=False))
    .with_columns(asn_iana_cat=get_asn_category(pl.col("asn_int")))
    .drop("asn_int")
    .join(
        ripe_asn_df.select(["asn", "as_name_long", "asn_ripe_location"]),
        on="asn",
        how="left",
    )
)
liu_exp_df = liu_df.filter(pl.col("value_type") == "explicit")
print(f"  {len(liu_df):,} rows total, {len(liu_exp_df):,} explicit", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Load RouteViews
# ---------------------------------------------------------------------------
t0 = _step("Loading RouteViews (jan-2026.txt)")
routeviews_raw_df = (
    pl.read_lines(
        "input_files/jan-2026.txt",
        name="community",
    )
    .with_columns(
        month=pl.lit("2026-01").cast(pl.Categorical),
        community=pl.col("community").replace(well_known_communities),
    )
    .pipe(parse_community_type)
    .pipe(_enrich_with_asn_category)
    .join(
        ripe_asn_df.select(["asn", "as_name_long", "asn_ripe_location"]),
        left_on="asn_from_community",
        right_on="asn",
        how="left",
    )
)
routeviews_df     = routeviews_raw_df.filter(pl.col("type") == "standard")
routeviews_lrg_df = routeviews_raw_df.filter(pl.col("type") == "large")
print(f"  {len(routeviews_raw_df):,} rows total | standard: {len(routeviews_df):,} | large: {len(routeviews_lrg_df):,}", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Load Brivaldo dataset
# ---------------------------------------------------------------------------
t0 = _step("Loading Brivaldo dataset (communities.db)")
brivaldo_df = (
    _load_brivaldo_from_db("input_files/communities.db")
    .with_columns(community=pl.col("community").replace(well_known_communities))
    .pipe(parse_community_type)
    .pipe(_enrich_with_asn_category)
    .join(
        ripe_asn_df.select(["asn", "as_name_long", "asn_ripe_location"]),
        left_on="asn_from_community",
        right_on="asn",
        how="left",
    )
)
print(f"  {len(brivaldo_df):,} rows loaded", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Load Krenc dataset
# ---------------------------------------------------------------------------
t0 = _step("Loading Krenc dataset (krenc_dataset.csv)")
krenc_df = (
    pl.read_csv("input_files/krenc_dataset.csv")
    .with_columns(community=pl.col("community").replace(well_known_communities))
    .pipe(parse_community_type)
    .pipe(_enrich_with_asn_category)
    .join(
        ripe_asn_df.select(["asn", "as_name_long", "asn_ripe_location"]),
        left_on="asn_from_community",
        right_on="asn",
        how="left",
    )
)
print(f"  {len(krenc_df):,} rows loaded", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Derive filtered passo5 views
# ---------------------------------------------------------------------------
t0 = _step("Deriving filtered passo5 views")
passo5_all_df = passo5_raw_df.filter(
    pl.col("first").str.contains(
        r"^(?:\d+)(?::(?:\d+|\d+(<[^>]*>)*\d*|\d*(<[^>]*>)*\d+))*$"
    )
)
passo5_std_df = passo5_all_df.filter(pl.col("type") == "standard")
passo5_lrg_df = passo5_all_df.filter(pl.col("type") == "large")
passo5_exp_df = (
    passo5_raw_df
    .filter(~pl.col("community").str.contains(r"<[^>]*>"))
    .filter(pl.col("type") == "standard")
)
print(f"  all: {len(passo5_all_df):,} | std: {len(passo5_std_df):,} | lrg: {len(passo5_lrg_df):,} | exp: {len(passo5_exp_df):,}", flush=True)
_done(t0)

# ---------------------------------------------------------------------------
# Coverage calculations — month to evaluate
# ---------------------------------------------------------------------------
MONTH = "2026-01"

rv_month     = routeviews_df.filter(pl.col("month") == MONTH)
rv_lrg_month = routeviews_lrg_df.filter(pl.col("month") == MONTH)
rv_all_month = routeviews_raw_df.filter(pl.col("month") == MONTH)
print(f"\nRouteViews slice for {MONTH}: standard={len(rv_month):,} | large={len(rv_lrg_month):,} | all={len(rv_all_month):,}", flush=True)

# — Our dataset, standard communities —
t0 = _step("match_communities: ours standard × routeviews standard")
_, routeviews_matched_passo5_std_df = match_communities(
    passo5_std_df, rv_month, how=join_ours_routeviews
)
_total   = len(routeviews_matched_passo5_std_df)
_matched = len(routeviews_matched_passo5_std_df.filter(pl.col("matched")))
_done(t0)
print(f"  standard {_matched:,}/{_total:,} ({_matched / _total:.2%})")
total_rv                = _total
our_coverage_explicit   = _matched
our_coverage_percentage = _matched / _total

# — Our dataset, large communities —
t0 = _step("match_communities: ours large × routeviews large")
_, routeviews_matched_passo5_lrg_df = match_communities(
    passo5_lrg_df, rv_lrg_month, how=join_ours_routeviews
)
_total   = len(routeviews_matched_passo5_lrg_df)
_matched = len(routeviews_matched_passo5_lrg_df.filter(pl.col("matched")))
_done(t0)
print(f"  large {_matched:,}/{_total:,} ({_matched / _total:.2%})")
our_coverage_explicit_lrg   = _matched
our_coverage_percentage_lrg = _matched / _total

# — Our dataset, all types —
t0 = _step("match_communities: ours all × routeviews all")
_, routeviews_matched_passo5_all_df = match_communities(
    passo5_all_df, rv_all_month, how=join_ours_routeviews
)
_total   = len(routeviews_matched_passo5_all_df)
_matched = len(routeviews_matched_passo5_all_df.filter(pl.col("matched")))
_done(t0)
print(f"  all {_matched:,}/{_total:,} ({_matched / _total:.2%})")
our_coverage_explicit_all   = _matched
our_coverage_percentage_all = _matched / _total

# — Our dataset, explicit + standard only —
t0 = _step("match_communities: ours explicit+standard × routeviews standard")
_, routeviews_matched_passo5_exp_df = match_communities(
    passo5_exp_df, rv_month, how=join_ours_routeviews
)
_total   = len(routeviews_matched_passo5_exp_df)
_matched = len(routeviews_matched_passo5_exp_df.filter(pl.col("matched")))
_done(t0)
print(f"  explicit & standard only {_matched:,}/{_total:,} ({_matched / _total:.2%})")
our_coverage_explicit_exp   = _matched
our_coverage_percentage_exp = _matched / _total

# — Communities in our dataset not in RouteViews —
t0 = _step("Computing communities unique to our dataset")
not_in_routeviews_df = passo5_all_df.join(routeviews_raw_df, on="community", how="anti")
_not_in_rv_count = len(not_in_routeviews_df)
_total_our_data  = len(passo5_all_df)
_done(t0)
print(f"  unique to our dataset: {_not_in_rv_count:,} / {_total_our_data:,} ({_not_in_rv_count / _total_our_data:.2%})")

# — Liu coverage —
t0 = _step("match_communities: liu × routeviews standard")
_, routeviews_matched_liu_df = match_communities(
    liu_df, rv_month, how=join_liu_routeviews
)
_total   = len(routeviews_matched_liu_df)
_matched = len(routeviews_matched_liu_df.filter(pl.col("matched")))
_done(t0)
print(f"  Liu {_matched:,}/{_total:,} ({_matched / _total:.2%})")
liu_coverage_explicit   = _matched
liu_coverage_percentage = _matched / _total

t0 = _step("match_communities: liu explicit × routeviews standard")
_, routeviews_matched_liu_exp_df = match_communities(
    liu_exp_df, rv_month, how=join_liu_routeviews
)
_total   = len(routeviews_matched_liu_exp_df)
_matched = len(routeviews_matched_liu_exp_df.filter(pl.col("matched")))
_done(t0)
print(f"  Liu explicit only {_matched:,}/{_total:,} ({_matched / _total:.2%})")
liu_exp_coverage_explicit   = _matched
liu_exp_coverage_percentage = _matched / _total

# — Brivaldo coverage —
t0 = _step("Computing Brivaldo coverage")
_A_comms = brivaldo_df.select("community").unique()
_B_comms = routeviews_df.select("community").unique()
_covered = _B_comms.join(_A_comms, on="community", how="inner")
brivaldo_coverage_explicit   = _covered.height
brivaldo_coverage_percentage = _covered.height / _B_comms.height
_done(t0)
print(f"  Brivaldo {brivaldo_coverage_explicit:,} / {_B_comms.height:,} covered ({brivaldo_coverage_percentage:.2%})")

# — Krenc coverage —
t0 = _step("Computing Krenc coverage")
_A_comms = krenc_df.select("community").unique()
_covered = _B_comms.join(_A_comms, on="community", how="inner")
krenc_coverage_explicit   = _covered.height
krenc_coverage_percentage = _covered.height / _B_comms.height
_done(t0)
print(f"  Krenc {krenc_coverage_explicit:,} / {_B_comms.height:,} covered ({krenc_coverage_percentage:.2%})")

# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------
def _build_coverage_chart(
    total_communities: int,
    counts: list[int],
    percentages: list[float],
    y_domain: list[int] | None = None,
) -> alt.LayerChart:
    _data = {
        "Dataset":    ["Ours", "Liu", "Brivaldo", "Krenc"],
        "Count":      counts,
        "Percentage": percentages,
    }
    _df = pl.DataFrame(_data).with_columns(
        label=pl.col("Percentage").round(2).cast(pl.Utf8) + "%"
    )

    _y_enc = (
        alt.Y("Count:Q", title="Number of Communities", scale=alt.Scale(domain=y_domain))
        if y_domain
        else alt.Y("Count:Q", title="Number of Communities")
    )

    _bars = (
        alt.Chart(_df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("Dataset:N", sort="-y", title="BGP Dataset"),
            y=_y_enc,
            color=alt.Color("Dataset:N", legend=None),
            tooltip=["Dataset", "Count", "Percentage"],
        )
        .properties(
            title="Coverage of Communities seen in RV and RIPE Collectors",
            width=500,
            height=300,
        )
    )

    _text = _bars.mark_text(
        dy=20, baseline="bottom", fontWeight="bold"
    ).encode(
        text=alt.Text("label:N"),
        color=alt.value("black"),
    )

    return (_bars + _text).configure(
        axis=alt.AxisConfig(labelFontSize=18, labelFontWeight="bold"),
        title=alt.TitleConfig(fontSize=22),
    )


# ---------------------------------------------------------------------------
# Chart 1 — normalised y-axis
# ---------------------------------------------------------------------------
t0 = _step("Saving coverage_normalised.pdf")
chart_coverage = _build_coverage_chart(
    total_communities=total_rv,
    counts=[our_coverage_explicit, liu_coverage_explicit,
            brivaldo_coverage_explicit, krenc_coverage_explicit],
    percentages=[our_coverage_percentage * 100, liu_coverage_percentage * 100,
                 brivaldo_coverage_percentage * 100, krenc_coverage_percentage * 100],
)
chart_coverage.save(os.path.join(OUTPUT_DIR, "coverage_normalised.pdf"))
_done(t0)
print(f"  total communities: {total_rv:,}")

# ---------------------------------------------------------------------------
# Chart 2 — y-axis scaled to total RouteViews communities
# ---------------------------------------------------------------------------
t0 = _step("Saving coverage_scaled.pdf")
chart_coverage_scaled = _build_coverage_chart(
    total_communities=total_rv,
    counts=[our_coverage_explicit, liu_coverage_explicit,
            brivaldo_coverage_explicit, krenc_coverage_explicit],
    percentages=[our_coverage_percentage, liu_coverage_percentage,
                 brivaldo_coverage_percentage, krenc_coverage_percentage],
    y_domain=[0, total_rv],
)
chart_coverage_scaled.save(os.path.join(OUTPUT_DIR, "coverage_scaled.pdf"))
_done(t0)
print(f"  total communities: {total_rv:,}")

# ---------------------------------------------------------------------------
# Semantic relations exploration
# ---------------------------------------------------------------------------
t0 = _step("Semantic relations exploration")
patterns = ["together", "requires", "overrides", "combined", "combination", "used with"]
regex = "|".join(patterns)
perhaps_df = passo5_raw_df.filter(
    pl.col("description").str.contains(regex)
).filter(pl.col("description").str.contains(":"))
_done(t0)
print(f"  communities with semantic relation keywords: {len(perhaps_df):,}")
print(perhaps_df)

print(f"\n[{time.strftime('%H:%M:%S')}] All done.", flush=True)
