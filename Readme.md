# BGPScout — BGP Community Dictionary Builder

BGPScout is a collection of Python scripts designed to automatically extract, process, and consolidate BGP community data from multiple sources into a structured CSV dictionary. It leverages the OpenAI API to parse and interpret community definitions found in IRR records, web pages, and IXP documentation.

---

## Table of Contents

- [Suggested Workflow](#suggested-workflow)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [OpenAI API Key Configuration](#openai-api-key-configuration)
- [Repository Structure](#repository-structure)
- [Scripts](#scripts)
  - [bgpscout_irr.py](#bgpscout_irrpy)
  - [bgpscout_url.py](#bgpscout_urlpy)
  - [bgpscout_peeringdb.py](#bgpscout_peeringdbpy)
  - [bgpscout_filter_pipeline.py](#bgpscout_filter_pipelinepy)
- [Semantic Tag Taxonomy](#semantic-tag-taxonomy)
- [Input Files and Directories](#input-files-and-directories)
- [Output Format](#output-format)

---

## Suggested Workflow

The scripts are designed to be used in sequence to build a clean, consolidated BGP community dictionary:

```
1. Extract communities from all sources:
   python3 bgpscout_irr.py irr.db
   python3 bgpscout_url.py urls.txt
   cd peeringdb-registers && python3 ../bgpscout_peeringdb.py && cd ..

2. Concatenate all output CSVs into one:
   cat communities_irr_*.csv communities_webcrawling_*.csv communities_peeringdb_*.csv > communities_all.csv

3. Run the filter pipeline (syntax validation + trusted-AS filtering):
   python3 bgpscout_filter_pipeline.py communities_all.csv trusted_as.txt

4. Final clean dictionary:
   communities_all_filtered.csv
```

---

## Prerequisites

- Python 3.8 or higher
- An active [OpenAI](https://platform.openai.com/) account with API access
- Internet access

---

## Installation

Clone the repository and install the required Python libraries:

```bash
git clone https://github.com/your-username/bgpscout.git
cd bgpscout
pip install openai requests backoff
```

---

## OpenAI API Key Configuration

> ⚠️ **This step is mandatory.** The scripts `bgpscout_irr.py`, `bgpscout_url.py`, and `bgpscout_peeringdb.py` all call the OpenAI API. Without a valid API key, they will not work.

The OpenAI client automatically reads the API key from the environment variable `OPENAI_API_KEY`. Set it in your terminal before running any script:

```bash
export OPENAI_API_KEY="sk-your-api-key-here"
```

To make this permanent (so you do not need to export it every session), add it to your shell configuration file:

```bash
# For bash users:
echo 'export OPENAI_API_KEY="sk-your-api-key-here"' >> ~/.bashrc
source ~/.bashrc

# For zsh users:
echo 'export OPENAI_API_KEY="sk-your-api-key-here"' >> ~/.zshrc
source ~/.zshrc
```

To verify the key is set correctly:

```bash
echo $OPENAI_API_KEY
```

> You can obtain your API key at: https://platform.openai.com/api-keys

---

## Repository Structure

```
bgpscout/
│
├── bgpscout_irr.py                  # Extracts BGP communities from IRR database files
├── bgpscout_url.py                  # Extracts BGP communities from web pages via URL list
├── bgpscout_peeringdb.py            # Extracts BGP communities from PeeringDB Markdown files
├── bgpscout_filter_pipeline.py      # Validates syntax and filters by trusted AS list
│
├── irr.db                           # IRR database dump with RPSL records
├── trusted_as.txt                   # List of trusted/allowed AS numbers (one per line)
├── urls.txt                         # List of URLs to scrape for BGP community data
│
└── peeringdb-registers/             # Directory containing PeeringDB route server pages
    ├── IXP-Name-1.md
    ├── IXP-Name-2.md
    └── ...
```

---

## Scripts

### bgpscout_irr.py

Reads an IRR (Internet Routing Registry) database file in RPSL format, splits it into individual AS records, and uses the OpenAI API to extract all BGP communities from each record.

- **Input:** An IRR database file (e.g., `irr.db`)
- **Output:** A CSV file named `communities_irr_<filename>_<timestamp>.csv` and a `.log` file

**Usage:**

```bash
python3 bgpscout_irr.py irr.db
```

**Output CSV columns:** `AS`, `AS Name`, `Community`, `Description`, `Internet Routing Registry (IRR)`

---

### bgpscout_url.py

Reads a plain-text file containing one URL per line, fetches each page's content as Markdown (via the [Jina Reader API](https://jina.ai/reader/)), and uses the OpenAI API to extract BGP communities from the page content. Large pages are automatically split into chunks for processing.

- **Input:** A text file with one URL per line (default: `sources.txt`; can be overridden via argument)
- **Output:** A CSV file named `communities_webcrawling_<timestamp>.csv` and a `.log` file

**Usage:**

```bash
# Using the default sources.txt file:
python3 bgpscout_url.py

# Using a custom file:
python3 bgpscout_url.py urls.txt
```

**Output CSV columns:** `AS`, `AS Name`, `Community`, `Description`, `Source URL`

---

### bgpscout_peeringdb.py

Scans the directory where the script is located for `.md` files (PeeringDB route server pages saved as Markdown) and uses the OpenAI API to extract BGP communities from each file. The filename is passed as context to help the model identify the IXP name.

- **Input:** All `.md` files present in the **same directory as the script** (e.g., inside `peeringdb-registers/`)
- **Output:** A CSV file named `communities_peeringdb_<timestamp>.csv` and a `.log` file

**Usage:**

```bash
cd peeringdb-registers
python3 ../bgpscout_peeringdb.py
```

> Alternatively, copy the script into the `peeringdb-registers/` directory and run it directly.

**Output CSV columns:** `AS`, `AS Name`, `Community`, `Description`, `PeeringDB`

---

### bgpscout_filter_pipeline.py

Validates and filters a BGP community CSV dictionary through 9 deterministic stages, in order:

1. **Column count** — rejects lines that do not have exactly 5 columns
2. **Blank cells** — rejects lines with any empty cell
3. **AS numeric** — rejects lines where the AS column is not a plain integer
4. **Community syntax** — rejects lines where the community does not match `A:B` or `A:B:C`
5. **Trusted-AS allow-list** — rejects lines whose AS number is not in the provided trusted-AS file
6. **AS kind** — rejects private, reserved, and documentation ASNs
7. **Toy ASN** — rejects well-known toy/example ASNs used in tutorials and labs
8. **Description quality** — rejects descriptions flagged as low-quality or non-operational extractions
9. **Placeholder normalisation** — rewrites community placeholders of the form `<DIGITsuffix>` to `DIGIT<suffix>` (e.g. `12345:<1abc>` → `12345:1<abc>`); applied only to lines that passed all previous stages

This script does **not** use the OpenAI API.

- **Input:**
  - A CSV dictionary file (5 columns, as produced by any extraction script)
  - A plain-text file with trusted AS numbers, one per line (e.g., `trusted_as.txt`)
- **Output:**
  - `<input_name>_filtered.csv` — lines that passed all 9 stages (with placeholders normalised)
  - `rejected_lines.csv` — all lines removed at any stage, with a 6th column containing a human-readable description of the rejection reason

**Usage:**

```bash
python3 bgpscout_filter_pipeline.py communities_all.csv trusted_as.txt
```

---

## Semantic Tag Taxonomy

Each community entry in the BGPScout dictionary is annotated with a **semantic tag** that describes the operational meaning of that community. Tags follow a structured hierarchical scheme with colon-separated components, for example:

- `information:location:geo_scope:city`
- `action:outbound:advertise:prepend:peer_targeting`

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

## Input Files and Directories

| File / Directory | Used by | Description |
|---|---|---|
| `irr.db` | `bgpscout_irr.py` | IRR database dump in RPSL format. Each AS record starts with an `aut-num:` line. |
| `urls.txt` | `bgpscout_url.py` | Plain-text file with one URL per line pointing to pages that document BGP communities. |
| `trusted_as.txt` | `bgpscout_filter_pipeline.py` | Plain-text file with one AS number per line (no `AS` prefix — just digits, e.g., `15169`). |
| `peeringdb-registers/` | `bgpscout_peeringdb.py` | Directory containing PeeringDB route server pages saved as `.md` files. Each file should represent one IXP. |

---

## Output Format

All extraction scripts produce CSV files. After the source column is appended, each line has **5 columns**:

| Column | Description |
|---|---|
| `AS` | Public AS number that owns the community (numeric only) |
| `AS Name` | Name of the AS or IXP |
| `Community` | Community value in `ASN:VALUE` or `ASN:VALUE1:VALUE2` format |
| `Description` | Human-readable description of the community's purpose (in English) |
| `Source` | Origin of the data (URL, `PeeringDB`, `Internet Routing Registry (IRR)`) |

---

> Each extraction script also generates a `.log` file with detailed diagnostics, token usage, and per-record results for auditing and debugging purposes.
