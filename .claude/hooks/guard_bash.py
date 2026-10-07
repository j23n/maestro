"""Logic of guard-bash.sh (PreToolUse on Bash). Reads the hook JSON on stdin."""
import json, os, re, shlex, subprocess, sys

def block(msg):
    print(f"Blocked: {msg}", file=sys.stderr)
    sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
if not cmd:
    sys.exit(0)

cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
try:
    root = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                          timeout=10).stdout.strip() or cwd
except Exception:
    root = cwd
root = os.path.realpath(root)

try:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    tokens = list(lex)
except ValueError:
    if re.search(r"\b(it)?content\b[^|;&\n]*\b(approve|reopen)\b", cmd):
        block("only the owner runs 'content approve' and 'content reopen' (docs/13 ADR-15). Ask them.")
    sys.exit(0)                                   # otherwise unparsable: leave it to the permission prompt

SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
commands, current = [], []
for t in tokens:
    if t in SEPARATORS:
        if current:
            commands.append(current)
        current = []
    else:
        current.append(t)
if current:
    commands.append(current)

# `content approve|reopen` as a command (uv run content …, .venv/bin/content …, python -m itcontent …),
# not as words inside an argument such as a commit message.
for c in commands:
    names = [os.path.basename(t) for t in c]
    for i, n in enumerate(names):
        if n in ("content", "itcontent") and any(x in ("approve", "reopen") for x in names[i + 1:]):
            block("only the owner runs 'content approve' and 'content reopen' (docs/13 ADR-15). Ask them.")

written = []
for c in commands:
    args = []
    i = 0
    while i < len(c):
        t = c[i]
        if t in REDIRECTS or re.fullmatch(r"\d?>>?", t):
            if i + 1 < len(c):
                written.append(c[i + 1])
            i += 2
            continue
        args.append(t)
        i += 1
    while args and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]) or args[0] in ("sudo", "command", "env", "nohup", "time")):
        args = args[1:]
    if not args:
        continue
    verb, rest = os.path.basename(args[0]), args[1:]
    files = [a for a in rest if not a.startswith("-")]
    if verb in ("rm", "mv", "tee", "truncate", "chmod", "chown", "unlink", "touch"):
        written += files
    elif verb == "sed" and any(a.startswith("-i") or a.startswith("--in-place") for a in rest):
        written += files
    elif verb == "perl" and any(re.match(r"^-[a-zA-Z]*i", a) for a in rest):
        written += files
    elif verb in ("cp", "rsync", "install", "ln") and files:
        written.append(files[-1])
    elif verb == "git" and rest and rest[0] in ("checkout", "restore", "rm", "mv"):
        written += [a for a in rest[1:] if not a.startswith("-")]

APPROVED = re.compile(r"""status:\s*["']?approved["']?""")

def approved(path):
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return False
    for i, line in enumerate(lines):
        if line.startswith("review:"):
            if APPROVED.search(line):
                return True
            for nxt in lines[i + 1:]:
                if nxt.strip() == "" or nxt.lstrip().startswith("#"):
                    continue
                if not nxt[:1].isspace():
                    break
                if APPROVED.search(nxt):
                    return True
            return False
    return False

for w in written:
    p = os.path.realpath(os.path.join(cwd, os.path.expanduser(w)))
    rel = os.path.relpath(p, root).replace(os.sep, "/").lower()
    if rel.startswith(".."):
        continue
    if (rel == "fixtures/fsrs" or rel.startswith("fixtures/fsrs/") or rel == ".claude/hooks" or rel.startswith(".claude/hooks/")
            or rel in (".claude/settings.json", ".claude/settings.local.json", "content/ids.lock")):
        block(f"{w} is protected (generated fixtures, the agent harness or ids.lock). Ask the owner.")
    if rel == "reviews/inbox" or rel.startswith("reviews/inbox/"):
        block(f"{w} is in reviews/inbox, the content lead's review files. Use 'uv run content review-import' to file a review; record resolutions in reviews/<scope>.yaml.")
    if rel.startswith("content/"):
        targets = [p]
        if os.path.isdir(p):
            targets = [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f.endswith((".yaml", ".yml"))]
        for t in targets:
            if os.path.isfile(t) and approved(t):
                block(f"{os.path.relpath(t, root)} is approved content. The owner must run 'content reopen' first.")
sys.exit(0)
