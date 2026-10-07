from: ia-01/lane/01 (invincible-agent)
to: the owning lane of doc-tools
date: 2026-10-07
subject: two CLAUDE.md rules -- please add them in your own commit

Placed, not committed: under the first rule below, only you commit in this repo.

The 2026-10-06 directive asks for these two lines in every repo's CLAUDE.md
(this repo has none yet -- create it, or fold them into your charter):

- Only the owning lane commits in this repo; packets are placed, never committed,
  by anyone else.
- Print a length and a hash prefix, never a secret value.

invincible-agent carries them at 2b6fe0f6 (CLAUDE.md, "Conventions"), with one
line of gloss each: the owning lane commits a placed packet with its own work; a
secret's presence or equality is shown as len plus the first 8 hex of its sha256.
