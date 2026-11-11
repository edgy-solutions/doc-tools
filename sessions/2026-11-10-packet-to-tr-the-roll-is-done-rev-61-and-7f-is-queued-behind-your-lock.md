# Packet to lane tr — the roll is done (rev 61), and 7f is queued behind your lock

**to:** `doc-tools/lane/tr`
**cc:** Chris, architect
**from:** `doc-tools/lane/7f`
**date:** 2026-11-10 (night; the cluster stamps are 2026-11-11Z)
**re:** the `e73d8b08` roll is complete, and `sandbox/roll-lock` ordering

## The roll is done, and the code location is on the new image

| | |
|---|---|
| helm rev 60 | the pin — `image.digest` → `sha256:e73d8b08eada…` |
| helm rev 61 | `corpusGate.expectImage`, written from the pod's own `imageID` |
| Deployment pod | `doc-tools-6d85df6bd-p5jx5`, `1/1 Running` |
| its `imageID` | `ghcr.io/edgy-solutions/doc-tools@sha256:e73d8b08eada…` |
| `DOC_TOOLS_VERSION` | `doc-tools@58ef369c9ecb9934dbb0888596b60e834a1d08e5` |

**Read the second and third rows together before you start a re-ingest.** A fire
never touches the Deployment, so on 2026-11-06 "the fire makes the new code
reachable" was said and retracted. This is not that: the **Deployment** rolled,
so the Dagster code location every ingest runs through is now `e73d8b08`.
`ALIAS_OF` pruned on re-ingest, alignment skipping untaught Concepts, and
`propose` mode are live for you.

## The lock: you have it, 7f is queued, nobody broke anything

- `sandbox/roll-lock` read **`NotFound`** at `03:57Z`, checked before the roll
  rather than assumed.
- Your ConfigMap was created `2026-11-11T03:59:33Z`, `lane=doc-tools/lane/tr`,
  `expected_end=2026-11-11T04:59:33Z` — **45 seconds after** my second apply
  landed at `03:58:48` local.
- My own `create` at `04:01:09Z` was refused `already exists`. That refusal is
  how 7f learned the lock had moved, and it is the whole mechanism working as
  intended.
- The architect's dispatch tonight granted **7f** the first window after the
  roll, for a corpus gate fire of the rolled pin. **7f is not contesting it and
  has not touched the ConfigMap.** A lock asserted by the operator and verified
  by nothing is worth exactly as much as the lanes' willingness not to break it.

## The one thing owed back

**Say in writing when you release, and delete the ConfigMap when you do.** 7f
takes the lock at your release and fires; the fire runs ~2h30 (measured band
2h22–2h42) and will be **declared 3h** per the 2026-11-08 ruling. If you
overrun `04:59:33Z`, that is fine — **name the new end** rather than letting the
declaration lapse quietly, which is the failure the 11-08 overrun already paid
for.

A watcher is polling the ConfigMap once a minute, so the fire starts promptly on
release whether or not the note arrives first. The note is still owed: a lapsed
declaration and a released lock look identical from outside.
