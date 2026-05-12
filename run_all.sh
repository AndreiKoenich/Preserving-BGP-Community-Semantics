#!/usr/bin/env bash
# run_all.sh
# Runs all BGP Communities analysis scripts in sequence.
# Must be executed from the directory that contains the scripts and input_files/.
#
# Usage:
#   chmod +x run_all.sh
#   ./run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colour helpers
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${CYAN}━━━ $* ${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
fail() { echo -e "${RED}✗ $*${NC}"; exit 1; }

# ── Pre-flight: verify required input files ───────────────────────────────────
step "Checking input files"
REQUIRED=(
    "input_files/communities.db"
    "input_files/our_dataset.csv"
    "input_files/krenc_dataset.csv"
    "input_files/semanticdic_total.json"
    "input_files/jan-2026.txt"
    "input_files/our-tags-2levelonly.csv"
    "input_files/tags_mapping_ours_brivaldo.csv"
    "input_files/tags_mapping_ours_krenc.csv"
)
for f in "${REQUIRED[@]}"; do
    if [[ ! -f "$f" ]]; then
        fail "Missing required input file: $f"
    fi
    ok "$f"
done

# ── Ensure output directory exists ───────────────────────────────────────────
mkdir -p output_files

# ── Script 1: Coverage heatmaps (AS × Value space) ───────────────────────────
step "Running coverage_charts.py"
uv run coverage_charts.py
ok "coverage_charts.py finished"

# ── Script 2: Confusion matrices ─────────────────────────────────────────────
step "Running confusion_matrixes.py"
uv run confusion_matrixes.py
ok "confusion_matrixes.py finished"

# ── Script 3: Public BGP data coverage (RouteViews-based) ─────────────────────────
step "Running public_bgp_data_coverage.py"
uv run public_bgp_data_coverage.py
ok "public_bgp_data_coverage.py finished"

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}━━━ All scripts completed. Output files:${NC}"
ls -lh output_files/
