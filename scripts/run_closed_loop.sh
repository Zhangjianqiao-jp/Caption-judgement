#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "usage: $0 V35_GENERATIONS.jsonl REFERENCE_SYSTEM CHALLENGER_SYSTEM SECRET_FILE OUT_DIR [RATING.json ...]" >&2
  echo "       set PROVENANCE_JSON=run/provenance.json for immutable model/data provenance" >&2
  exit 2
fi

input=$1
reference=$2
challenger=$3
secret=$4
output=$5
shift 5

mkdir -p "$output"
provenance_args=()
if [[ -n "${PROVENANCE_JSON:-}" ]]; then
  provenance_args=(--provenance "$PROVENANCE_JSON")
fi
caption-judge adapt --input "$input" --output "$output/generations.jsonl"
caption-judge build-packets --generations "$output/generations.jsonl" \
  --comparison "$reference=>$challenger" --secret-file "$secret" --group-size 3 \
  "${provenance_args[@]}" \
  --public "$output/blind_packets.jsonl" --private "$output/private_mapping.jsonl" \
  --manifest "$output/packet_manifest.json"
caption-judge render-prompts --packets "$output/blind_packets.jsonl" --output "$output/judge_prompts.jsonl"
caption-judge audit --generations "$output/generations.jsonl" --packets "$output/blind_packets.jsonl" \
  --mapping "$output/private_mapping.jsonl" --output "$output/audit.json"
caption-judge diversity --generations "$output/generations.jsonl" --output "$output/diversity.json"

if [[ $# -gt 0 ]]; then
  caption-judge aggregate --mapping "$output/private_mapping.jsonl" --ratings "$@" "${provenance_args[@]}" --output "$output/aggregate.json"
  caption-judge report --aggregate "$output/aggregate.json" --audit "$output/audit.json" \
    --diversity "$output/diversity.json" --plots-dir "$output/plots" --output "$output/REPORT.md"
else
  caption-judge rating-template --packets "$output/blind_packets.jsonl" --rater-id replace-me \
    --output "$output/rating_template.json"
fi
