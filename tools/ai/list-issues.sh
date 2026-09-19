#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

gh issue list \
  --state open \
  --limit 100 \
  --json number,title,labels,assignees,updatedAt,url
