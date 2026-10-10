#!/bin/sh
# Links a pull request to the issue it finishes, so that merging it closes the issue, and checks
# the link (j23n.md, "Pull requests"). Run it in the repository's checkout, with gh signed in:
#   .apple-ci/claude/link-pr.sh ISSUE PR
#   .apple-ci/claude/link-pr.sh --remove ISSUE PR
# A copy of j23n/apple-ci's claude/link-pr.sh: don't edit it, change apple-ci.
set -eu

mutation=addCloseIssueReferences
if [ "${1:-}" = --remove ]; then
  mutation=removeCloseIssueReferences
  shift
fi
usage() { echo "usage: link-pr.sh [--remove] ISSUE PR (both numbers)" >&2; exit 2; }
[ $# -eq 2 ] || usage
case "$1" in '' | *[!0-9]*) usage ;; esac
case "$2" in '' | *[!0-9]*) usage ;; esac
issue=$1
pr=$2

issue_id=$(gh issue view "$issue" --json id -q .id)
pr_id=$(gh pr view "$pr" --json id -q .id)
gh api graphql >/dev/null \
  -f query="mutation(\$issue: ID!, \$prs: [ID!]!) { $mutation(input: {issueId: \$issue, pullRequestIds: \$prs}) { issue { number } } }" \
  -f issue="$issue_id" -f "prs[]=$pr_id"

closes=$(gh pr view "$pr" --json closingIssuesReferences -q '.closingIssuesReferences[].number')
if printf '%s\n' "$closes" | grep -qx "$issue"; then linked=true; else linked=false; fi
if [ "$mutation" = addCloseIssueReferences ]; then
  $linked || { echo "#$pr still doesn't close #$issue" >&2; exit 1; }
  echo "#$pr closes #$issue when it's merged"
else
  $linked && { echo "#$pr still closes #$issue" >&2; exit 1; }
  echo "#$pr no longer closes #$issue"
fi
