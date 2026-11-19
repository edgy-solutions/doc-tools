# ADR-0205 — print a length and a hash prefix, never a secret value

**Status:** accepted + built
**Date:** carried as a standing convention since the 2026-10-06 fleet directive · recorded
2026-11-18
**Deciders:** the 2026-10-06 fleet directive, placed in `CLAUDE.md` by packets from
`ia-01/lane/01` and `ia-gov/lane/gov` (`CLAUDE.md:1-8`)
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `CLAUDE.md:17-21` (§Conventions); `tools/README.md:22-27`; built as
`tools/drift_check.py:1-6`, `:12`, `:16-18`, `:29` and `tools/preroll_diff.py:1-7`, `:22`,
`:32-37`, `:43-71`
**Related:** [ADR-0204](ADR-0204-show-the-values-diff-before-a-roll.md) (the roll diff that
obeys it), [ADR-0175](ADR-0175-proprietary-prompt-text-is-not-committed.md)

## Context

Agents and operators in this repo routinely need to answer three questions about a credential:
is it set, did it change, and is it the same on both sides of a comparison. All three can be
answered without the value. The convenient way to answer them is to print the value, and that
convenience has already cost this repo a disclosure.

**It is not hypothetical here: a drift script in this repo once printed three live credentials
into a transcript, and the transcript is not editable** (`CLAUDE.md:19-21`,
`tools/README.md:24-26`). Nothing can be withdrawn afterwards. There is no edit, no redaction
pass and no expiry on a transcript — the only control available is the one applied *before* the
print.

The same shape has recurred since from a read-only angle: a grep for credential **key names**
with the matching lines shown echoed the values beside them. Reading is enough to disclose; it
does not take a write, a render or a deploy.

## Decision

**A secret's presence or equality is shown as `len=N sha256:XXXXXXXX` — the length, and the
first 8 hex of the sha256 of the value — and the value itself is never printed.**

- The form is exactly that: `len=N sha256:XXXXXXXX`, first 8 hex (`CLAUDE.md:17-19`).
- It answers the three questions that are actually asked. *Set?* `N > 0`. *Changed?* the pair
  moved. *Equal on both sides?* the pairs match. None of those needs the value.
- Redaction is applied **before any output**, not to output already produced
  (`tools/preroll_diff.py:3-4`). A filter downstream of a print is not this rule.
- **Built, two ways.** `tools/drift_check.py` reads helm user-supplied values as JSON on stdin
  and fingerprints **every** leaf except the two digests a pin bump has to move — an allowlist,
  so a key nobody anticipated is redacted by default rather than by omission (`:12`, `:29`).
  `tools/preroll_diff.py` redacts on a secret-ish key-name substring **or** position inside a
  `kind: Secret` body's `data`/`stringData` block, and redacts **both sides** of the diff before
  anything reaches the output (`:22`, `:43-71`, `:88`).
- An environment variable that carries a credential is **named**, never valued. Naming the key
  is how a record says a thing is configured.
- A digest, a count, a rate, a length and a file path are not secrets and are shown in full.

## Consequences

- An equality can be *demonstrated* in a report without a disclosure, which is what makes the
  rule adoptable: it does not ask anyone to stop checking, only to stop printing.
- A fingerprint is a one-way claim. A reader cannot recover the value, and cannot tell a
  well-known default from a live credential by looking — the length is the only hint. Classifying
  a value therefore still requires a script that prints the pair and nothing else, never a grep
  with lines shown.
- The redactors are allowlist-shaped on the one side (`drift_check.py` shows two digests, hides
  everything else) and denylist-shaped on the other (`preroll_diff.py` matches key-name
  substrings). The second has a gap by construction — a credential under a name that matches
  none of `TOKEN`, `SECRET`, `KEY`, `PASSWORD`, `PASS`, `CRED` and outside a `Secret` body would
  pass through. The `kind: Secret` test is the second leg that covers the common case of that
  gap, and widening the substring list is cheap when a new name appears.
- This record obeys its own rule: it names no credential, no key's value, and no environment
  variable's value.

## Alternatives considered

- **Print the value when it is "only a dev placeholder".** Rejected by the incident: the
  classification is made *after* the print, and the print is permanent. A value cannot be
  demoted retroactively.
- **Redact after the fact.** Impossible, and it is the reason the rule exists: a transcript is
  not editable.
- **A full sha256 rather than 8 hex.** Not recorded as considered. 8 hex is what the convention
  fixes and what both tools emit, and a longer prefix buys nothing for the three questions above.
- **Omit secret-bearing keys from the output entirely.** Rejected implicitly by both tools,
  which print the fingerprint: omission would hide that a key exists and that it changed, which
  is exactly the information a pre-roll diff is for.
