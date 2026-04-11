# Maestro — Claude Code Instructions

## Worktree Discipline

When working inside a git worktree, stay in that worktree. This applies to
every tool call, agent spawn, and file read/write for the entire session:

- **Never** `cd` to the main repo or another worktree.
- **Sub-agents** must receive the worktree path explicitly and work only there.
- If you need information from outside the worktree, **ask the user** instead
  of navigating there yourself.
