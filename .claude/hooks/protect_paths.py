"""Logic of protect-paths.sh (PreToolUse on Edit|Write|MultiEdit|NotebookEdit). Reads the hook JSON on stdin."""
import json, os, re, subprocess, sys

def block(msg):
    print(f"Blocked: {msg}", file=sys.stderr)
    sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception:
    block("the hook input could not be parsed, so the edit can't be checked. Try again.")

tool_input = data.get("tool_input") or {}
path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
if not path:
    sys.exit(0)
cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
path = os.path.realpath(os.path.join(cwd, path))           # resolves .., symlinks; absolute paths stay absolute

d = os.path.dirname(path)
while d and not os.path.isdir(d):
    d = os.path.dirname(d)
try:
    root = subprocess.run(["git", "-C", d or "/", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=10).stdout.strip()
except Exception:
    root = ""
root = os.path.realpath(root or os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
rel = os.path.relpath(path, root)
if rel.startswith(".."):
    sys.exit(0)                                              # outside the repo (scratch files): not ours to guard
r = rel.replace(os.sep, "/").lower()                         # APFS is case-insensitive
base = os.path.basename(r)

if r.startswith("fixtures/fsrs/"):
    block("fixtures/fsrs is generated from py-fsrs (fixtures/README.md). Ask the owner.")
if r in (".claude/settings.json", ".claude/settings.local.json") or r.startswith(".claude/hooks/"):
    block("the agent harness is owner-only. Propose changes in docs/13 under 'Proposed changes'.")
if r.startswith("reviews/inbox/"):
    block("reviews/inbox holds the content lead's review files exactly as sent. Record resolutions in reviews/<scope>.yaml; 'content review-import' files new reviews.")
if r == "content/ids.lock":
    block("content/ids.lock is written by release builds ('content build --release'), never by hand.")
is_licence = re.match(r"^(licen[cs]e|copying|ofl)", base) is not None or base.endswith("-ofl.txt")
if r.startswith("licenses/") or (is_licence and (r.startswith("design/fonts/") or r.startswith("pipeline/data/"))):
    block("licence files of bundled fonts and reference data are owner-only.")

APPROVED = re.compile(r"""status:\s*["']?approved["']?""")

def review_is_approved(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("review:"):
            if APPROVED.search(line):                         # flow style: review: {status: approved, …}
                return True
            for nxt in lines[i + 1:]:                         # block style: indented keys below
                if nxt.strip() == "" or nxt.lstrip().startswith("#"):
                    continue
                if not nxt[:1].isspace():
                    break
                if APPROVED.search(nxt):
                    return True
            return False
    return False

if r.startswith("content/") and r.endswith((".yaml", ".yml")):
    if os.path.isfile(path):
        try:
            current = open(path, encoding="utf-8").read()
        except Exception:
            block(f"{rel} could not be read to check its review status.")
        if review_is_approved(current):
            block(f"{rel} is approved by the content lead (review.status: approved). The owner must run 'content reopen' first.")
    # Only 'content approve' may set the approved status.
    new_texts = [tool_input.get("content") or "", tool_input.get("new_string") or ""]
    new_texts += [e.get("new_string") or "" for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    if any(APPROVED.search(t) for t in new_texts):
        block("only the owner's 'content approve' may set review.status to approved.")
sys.exit(0)
