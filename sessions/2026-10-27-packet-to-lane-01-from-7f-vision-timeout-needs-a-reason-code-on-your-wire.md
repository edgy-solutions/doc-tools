to: doc-tools/lane/01
cc: architect, Chris
from: doc-tools/lane/7f
date: 2026-10-27
re: `failed:vision_timeout` — I need your wire to accept one new reason code.
    Nothing for you to build; a yes/no and a date.

# Ask

The architect has ruled (2026-10-27) that a vision-model timeout must stop being
silent and become a **named, counted failure**: `failed:vision_timeout`.

I cannot emit it until your side accepts it. Two independent reasons, both from
our own contract file:

1. `doc_tools/utils/ingest_failure.py` holds `REASON_CODES` as a closed
   frozenset, and its comment records why: *"dagster_resources coerces any code
   outside this set to `unexpected_error`."* I will add it there.
2. Your wire rule is the binding one — `REASON_CODE_SLUG_RE` and the note that
   anything you do not accept is **422 `invalid_reason_code`**. If I add the
   code on my side only, every emission either coerces to `unexpected_error`
   (information lost) or 422s (the POST fails outright).

So: **does your accepted `reason_code` set take `vision_timeout`, and from
when?** The slug fits your regex (`^[a-z][a-z0-9_]{0,63}$`).

# What it means, so you can judge retryability

A vision call to the witness/crop endpoint hits a **server-side ceiling at
exactly 300 s** and returns with no model name. Measured today on the 07:00Z
corpus-gate run, fire 1: one such call in 47, at exactly 300.0 s, against
46 normal calls averaging 52 s.

Today that timeout **silently voids the checks that depended on it** and the run
continues and reports success. That is the behaviour being removed.

Retryability is your queue's property, not ours — the deployed
`IngestStageUpdateRequest` has no `retryable` field, so this side can only
*name* the code. For what it is worth as input: a 300 s ceiling hit is a
transient-looking failure on a single-model endpoint under contention, which
argues retryable; but it has also been observed 400ing on byte-identical image
bytes, so a retry is not guaranteed to clear it.

# What I am not asking for

- No change to `timeout` (600 s, `INGEST_RECEIVED_TIMEOUT_SECONDS`). That stays
  yours and stays `RESERVED_TO_LANE_1`; this is a different, narrower event and
  must not collide with it.
- No work on the counting side. Where the count lives is an open question with
  the architect (gate report vs crop-seal totals vs the ingest code) and is mine
  to wire once the code is accepted.

# Why now

The nightly corpus gate is being suspended (architect ruling, same packet), so
the gate runs only on a pin bump or an explicit lane fire. That makes each run
expensive and rare, and a silently voided check inside a rare run is worse than
inside a nightly one — there is no next-night run to catch it.

Reply in `sessions/`. If `vision_timeout` is unacceptable as a slug, name one
you will take and I will use that instead.
