#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: $0 ISSUE_NUMBER" >&2
    exit 2
fi

ISSUE="$1"

case "$ISSUE" in
    ''|*[!0-9]*)
        echo "invalid issue number: $ISSUE" >&2
        exit 2
        ;;
esac

cd "$(git rev-parse --show-toplevel)"

gh issue view "$ISSUE" \
  --json number,title,body,state,labels,assignees,comments,updatedAt,url
