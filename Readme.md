# BGP Communities — Analysis Scripts

Scripts for analysing and comparing BGP community datasets.
All scripts are self-contained and managed by [`uv`](https://docs.astral.sh/uv/), which handles dependency installation automatically.

---

## Requirements

- [`uv`](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Python ≥ 3.11 (fetched automatically by `uv` if needed)

No manual `pip install` or virtual environment setup is required.

---

## Directory layout

```
.
├── input_files/                    # All input data (see section below)
│   ├── communities.db
│   ├── our_dataset.csv
│   ├── krenc_dataset.csv
│   ├── semanticdic_total.json
│   ├── jan-2026.txt
│   ├── our-tags-2levelonly.csv
│   ├── tags_mapping_ours_brivaldo.csv
│   └── tags_mapping_ours_krenc.csv
│
├── output_files/                   # Created automatically on first run
│   ├── coverage_normalised.pdf
│   ├── coverage_scaled.pdf
│   ├── coverage-count-ours.pdf
│   ├── coverage-count-brivaldo.pdf
│   ├── coverage-count-liu.pdf
│   ├── coverage-count-krenc.pdf
│   ├── ours_krenc_matrix.pdf
│   └── krenc_liu_matrix.pdf
│
├── coverage_bar_charts.py          # Script 1
├── coverage_charts.py              # Script 2
├── confusion_matrixes.py           # Script 3
└── run_all.sh                      # Runs all three scripts in sequence
```

---

## Running everything at once

```bash
chmod +x run_all.sh
./run_all.sh
```

The shell script checks that all required input files are present, then runs the three analysis scripts in the correct order. It stops immediately and reports an error if any file is missing or any script fails.

---

## Running scripts individually

```bash
uv run coverage_bar_charts.py
uv run coverage_charts.py
uv run confusion_matrixes.py
```

Each script reads from `input_files/` and writes its output to `output_files/`, creating the directory if it does not exist. Pre-existing files in `output_files/` with different names are never deleted.

---

## Scripts

### `coverage_bar_charts.py`

Measures how many communities observed in RouteViews (January 2026) are documented in each of the four datasets (Ours, Liu, Brivaldo, Krenc), producing two bar-chart PDFs:

| Output file | Description |
|---|---|
| `coverage_normalised.pdf` | Bar chart with a free y-axis, showing raw matched counts and percentage labels |
| `coverage_scaled.pdf` | Same bars but the y-axis is anchored to the total number of RouteViews communities, making the absolute gap visible |

**Inputs used:** `our_dataset.csv`, `communities.db`, `semanticdic_total.json`, `krenc_dataset.csv`, `jan-2026.txt`

**Processing highlights:**
- Loads RouteViews communities from `jan-2026.txt`, classifying each as standard, extended, or large.
- Replaces well-known community values (e.g. `65535:666`) with their IANA names before matching.
- Matches Ours and Liu using regex patterns (communities with parameterised values like `<value>` are expanded to regexes and matched against the RouteViews strings).
- Matches Brivaldo and Krenc by exact community string intersection.
- Annotates each ASN with its IANA category (assignable, private, reserved, documentation, unallocated).

---

### `coverage_charts.py`

Generates one AS × Community Value density heatmap per dataset, visualising which regions of the 16-bit AS number / 16-bit community value space each dataset covers.

| Output file | Description |
|---|---|
| `coverage-count-ours.pdf` | Heatmap for the Ours dataset |
| `coverage-count-brivaldo.pdf` | Heatmap for the Brivaldo dataset |
| `coverage-count-liu.pdf` | Heatmap for the Liu dataset |
| `coverage-count-krenc.pdf` | Heatmap for the Krenc dataset |

**Inputs used:** `our_dataset.csv`, `communities.db`, `semanticdic_total.json`, `krenc_dataset.csv`

**Processing highlights:**
- Brivaldo communities are read directly from `communities.db` via SQLite (no CSV intermediary).
- Liu communities are derived from `semanticdic_total.json` at runtime: the JSON is flattened into records and regex-based community values are expanded to explicit numeric strings before plotting.
- Both axes span `[0, 65535]`, binned into 400 buckets each; colour encodes community count per bin using the plasma colour scale.

---

### `confusion_matrixes.py`

Compares semantic label taxonomies across datasets by computing two confusion matrices.

| Output file | Description |
|---|---|
| `ours_krenc_matrix.pdf` | Ours labels (collapsed to `action` / `info`) vs. Krenc tags |
| `krenc_liu_matrix.pdf` | Liu semantics (collapsed to `action` / `info`) vs. Krenc tags |

**Inputs used:** `our_dataset.csv`, `krenc_dataset.csv`, `semanticdic_total.json`

**Processing highlights — Ours × Krenc:**
- Ours dataset is sanitised: only standard numeric communities (`ASN:value`) are kept; communities whose label is inconsistent across ASes are discarded.
- Ours semantic tags are collapsed: `information:*` → `info`, everything else → `action`.
- The collapsed labels are compared against Krenc's `tag` column after an inner join on `community`.

**Processing highlights — Krenc × Liu:**
- Krenc communities are parsed into first/second/third parts and classified as standard, extended, or large.
- Liu communities are loaded from `semanticdic_total.json`, regex values are expanded, and each entry is annotated: `semantic_type == "tag"` → `action=False`, all other types → `action=True`.
- After joining Krenc × Liu on `(ASN, community value)`, the `expected_krenc_tag` is derived: if any matching Liu entry expects an action, the community is labelled `action`, otherwise `info`.
- The derived label is compared against Krenc's own tag.

---

## Input files

### `our_dataset.csv`
The reference dataset produced as part of this research. Each row documents one BGP community belonging to a specific AS, with a structured semantic label and optional qualifiers.

Key columns:

| Column | Description |
|---|---|
| `asn` | Autonomous System Number that defined the community |
| `community` | Community string in `ASN:value` format (may contain `<param>` placeholders for parametric communities) |
| `description` | Human-readable description of the community's purpose |
| `structure_tag` | Structural classification (e.g. `standard:numeric`, `standard:parametric`) |
| `semantic_tag` | Hierarchical semantic label (e.g. `action:blackhole`, `information:location`) |
| `qualifiers` | Optional modifiers such as target peer scope (e.g. `all_peers`, `peer_targeting`) |
| `model_confidence` | Confidence level assigned during labelling |

---

### `communities.db`
SQLite database from the Brivaldo dataset containing BGP communities and their type classifications.

Source: <https://github.com/TopoMapping/bgp-action-communities/blob/main/data/communities.db>

Relevant tables:

- **`community`** — one row per community entry, with columns `name` (the community string), `type` (foreign key to `type.id`), `level`, and `comment`.
- **`type`** — lookup table mapping type IDs to type names (e.g. `traffic engineering`, `geolocation`, `exchange`).

The scripts query both tables via a JOIN at runtime; no CSV export step is needed.

---

### `semanticdic_total.json`
The Liu dataset: a nested JSON dictionary mapping ASNs to their documented BGP communities and semantic annotations.

Source: <https://github.com/internetsys/community_dictionary/blob/main/results/dictionary/semanticdic_total.json>

Top-level structure: `{ "<ASN>": { "<semantic_type>": <content> } }`.
Semantic types include `tag`, `blackhole`, `pref`, `prepend`, and `sel_ann`.
Community values may be `"explicit"` (a concrete number) or `"regular"` (a Python regex pattern to be expanded).

---

### `krenc_dataset.csv`
Dataset from Krenc et al. (CAIDA), inferred from BGP data collected in May 2023. Each row maps one community string to a coarse semantic tag (`action` or `info`).

Source: <https://users.caida.org/~tkrenc/communityinference/2023050x.communityinference.txt.bz2>

Key columns:

| Column | Description |
|---|---|
| `community` | Community string in `ASN:value` format |
| `tag` | Coarse semantic label: `action` or `info` |

---

### `jan-2026.txt`
A plain-text list of BGP community strings (one per line) observed in RouteViews and RIPE RIS collectors in January 2026. Used as the universe of "communities seen in the wild" for coverage calculations in `coverage_bar_charts.py`.

Each line is a raw community string such as `1234:5678` or `65535:666`. Well-known communities are substituted with their IANA names before processing.

---

### `our-tags-2levelonly.csv`
A flat list (no header) of all semantic tags used in the Ours dataset, restricted to the first two levels of the hierarchy (e.g. `action:blackhole`, `information:location`). Used as a controlled vocabulary for label validation and chart ordering.

Example entries: `action:accept`, `action:blackhole`, `information:location`, `unknown`.

---

### `tags_mapping_ours_brivaldo.csv`
A crosswalk table mapping Ours semantic tags to their closest equivalent in the Brivaldo taxonomy.

Columns:

| Column | Description |
|---|---|
| `OUR_TAG` | Full hierarchical tag from the Ours dataset (e.g. `outbound:action:suppress:prepend`) |
| `BRIVALDO_TAG` | Corresponding Brivaldo type name (e.g. `traffic engineering`, `geolocation`) |

---

### `tags_mapping_ours_krenc.csv`
A crosswalk table mapping Ours semantic tags to their closest equivalent in the Krenc taxonomy.

Columns:

| Column | Description |
|---|---|
| `OUR_TAG` | Tag from the Ours dataset (e.g. `action:blackhole`, `information:location`) |
| `KRENC_TAG` | Corresponding Krenc label: `action` or `information` |

---

## Notes

- All scripts are idempotent: re-running them overwrites existing output files with the same names and leaves all other files in `output_files/` untouched.
- Liu regex expansion (in `coverage_charts.py` and `confusion_matrixes.py`) may take several minutes depending on the number of regex patterns in `semanticdic_total.json`.
- The `coverage_bar_charts.py` script also prints per-dataset coverage statistics to stdout, which can be useful for a quick sanity check before inspecting the PDFs.

## About Semantic Tag Taxonomy in Our Dataset

Each community entry in our dictionary (our_dataset.csv) is annotated with a **semantic tag** that describes the operational meaning of that community. Tags follow a structured hierarchical scheme with colon-separated components, for example:

- `information:location`
- `outbound:action:advertise:prepend:peer_targeting`

The taxonomy is organised into three top-level categories:

| Category | Description |
|---|---|
| `information` | The community carries metadata about a route (origin, type, location, validation status, etc.) without directly triggering a routing action |
| `action` | The community instructs a router to perform a specific routing operation (announce, suppress, prepend, blackhole, etc.), scoped to a direction and a target |
| `unknown` | The community's semantics could not be determined or do not fit any defined category |

The complete tree of valid tag values is shown below. Inline comments describe the meaning of each node.

```
semantic
│
├── information                        # Route carries informational metadata
│   ├── route_source                   # Identifies who originated or sent the route
│   │   └── source_scope
│   │       ├── asn                    # A specific AS number
│   │       ├── customer
│   │       ├── peer
│   │       ├── peer_group
│   │       ├── transit
│   │       ├── upstream
│   │       ├── downstream
│   │       ├── ixp
│   │       ├── internal
│   │       └── pop                    # Point of Presence
│   │
│   ├── route_type                     # Classifies the functional role of the route
│   │   └── (examples)
│   │       ├── self-originated
│   │       ├── locally originated
│   │       ├── customer route
│   │       ├── peer route
│   │       └── transit route
│   │
│   ├── location                       # Geographic tagging of the route
│   │   └── geo_scope
│   │       ├── international
│   │       ├── continent
│   │       ├── country
│   │       ├── region
│   │       ├── city
│   │       └── metro
│   │
│   ├── route_tag                      # Generic tag/mark with no stronger assignable semantics
│   │
│   ├── validation                     # Generic route validation / sanity / hygiene signal
│   │
│   ├── validation_rpki                # Route validity derived from RPKI
│   │
│   ├── validation_irr                 # Route validity derived from IRR
│   │
│   ├── performance                    # Network performance or cost metadata
│   │   └── metric
│   │       ├── rtt
│   │       ├── latency
│   │       ├── quality
│   │       └── cost
│   │
│   ├── security_state                 # Security-related route classification
│   │
│   └── mitigation_state               # DDoS or attack mitigation status
│
├── action                             # Community triggers a routing operation
│   └── action_model
│       │
│       ├── outbound                   # Operation applied when advertising routes to peers
│       │   ├── advertise              # Announce the route
│       │   │   ├── modifier
│       │   │   │   ├── prepend        # Add AS-PATH prepends
│       │   │   │   ├── med            # Set MED value
│       │   │   │   └── more_specific  # Advertise a more-specific prefix
│       │   │   └── scope
│       │   │       ├── peer_targeting # A specific peer or set of peers
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── suppress               # Withdraw or stop advertising the route
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   └── restrict               # Limit advertisement scope (e.g. no-export)
│       │       └── scope
│       │           ├── peer_targeting
│       │           ├── all_peers
│       │           ├── all_upstreams
│       │           ├── all_customers
│       │           └── l3vpn_evpn
│       │
│       ├── inbound                    # Operation applied when receiving routes from peers
│       │   ├── accept                 # Accept the route
│       │   │   ├── modifier
│       │   │   │   └── localpref      # Set Local Preference
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── reject                 # Reject / drop the route
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── validate               # Trigger route validation procedure
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── blackhole              # Trigger traffic blackholing (RTBH)
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── scrubbing              # Redirect traffic to a scrubbing centre
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── flowspec               # Trigger a FlowSpec rule
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   └── next_hop_steering      # Override next-hop for traffic engineering
│       │       └── scope
│       │           ├── peer_targeting
│       │           ├── all_peers
│       │           ├── all_upstreams
│       │           ├── all_customers
│       │           └── l3vpn_evpn
│       │
│       └── both                       # Operation applies to both inbound and outbound
│           ├── accept
│           │   └── scope
│           │       ├── peer_targeting
│           │       ├── all_peers
│           │       ├── all_upstreams
│           │       ├── all_customers
│           │       └── l3vpn_evpn
│           │
│           ├── advertise
│           │   └── scope
│           │       ├── peer_targeting
│           │       ├── all_peers
│           │       ├── all_upstreams
│           │       ├── all_customers
│           │       └── l3vpn_evpn
│           │
│           └── restrict
│               └── scope
│                   ├── peer_targeting
│                   ├── all_peers
│                   ├── all_upstreams
│                   ├── all_customers
│                   └── l3vpn_evpn
│
└── unknown                            # Semantics could not be determined
    ├── unknown                        # Completely unclassifiable
    ├── inbound:unknown                # Direction known, operation unknown
    ├── outbound:unknown
    ├── both:unknown
    ├── inbound:action:unknown         # Direction and action class known, specifics unknown
    ├── outbound:action:unknown
    ├── both:action:unknown
    └── information:unknown            # Information community, specifics unknown
```

---
