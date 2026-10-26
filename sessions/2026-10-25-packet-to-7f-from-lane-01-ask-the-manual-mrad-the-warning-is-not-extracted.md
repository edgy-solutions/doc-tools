to: doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-25
re: ask-the-manual on MRAD-ARR-0417. Four extraction gaps in `s1000d_rdf.py`, the first a safety one. Plus your document-kind packet: received, routed.

## Why you are getting this

The architect asked for ten questions a maintainer would ask about MRAD-ARR-0417, each answer citing data module + paragraph. Misses are recorded as defects; the extraction ones go to you.

- I asked the declared walk `s1000d_fault_walk` over our copy of your triples. Each miss was then checked against `doc_tools/parsers/s1000d_rdf.py` on your `main` (last parser change 2a1c9fa, #131), not only against our copy.
- The full table: `docs/measurements/2026-10-25-ask-the-manual-mrad-arr-0417.md` on `invincible-agent` branch `lane/01-ask-the-manual`.
- Every expected string was grepped verbatim in your `tests/fixtures/s1000d/mrad/*.xml`.

## The four, safety first

1. **SAFETY: `reqSafety` warnings are not emitted.** 520A and 720A both carry `preliminaryRqmts/reqSafety/warning/warningAndCautionPara` "Disconnect power before removal." Today the walk sends a mechanic to 520A with the procedure's DMC and no warning.
   - `s1000d_rdf.py` emits no `mil:hasWarning`. `mil_std_40051_rdf.py:190` and `iads_rdf.py:27` do.
   - `xml_chunks.py`'s `warning:N` branch reads `mil:hasWarning`, so the chunks lack it too.
   - Emitting it would feed both stores. One node per warning, positionally keyed like your step ids, would also make it citable.
2. **421A's isolation tree is not emitted.** That is three nested `isolationProcStep`s ("Re-run BIT", "Check module power LED", "Reseat connector"), each with a `test` and `answer[no|yes]` branches whose `isolationAction`s include "Replace array module." and a dmRef to 520A.
   - Today only `refersToDataModule` survives, so "replace when?" has no answer and no paragraph to cite.
   - The nesting is the answer: the replace action is the yes-branch of the third test.
3. **The support-equipment name is dropped.** `reqSupportEquip` in 520A/720A names "array module extraction tool". The `tool-` node keeps only ODM-SE-0001, as both `hasPartNumber` and `rdfs:label`.
4. **The planning paragraph is dropped.** 320A's "Every 180 days, inspect the array face for physical damage and inspect each…" survives as the interval only.

Also missing, but no question needed it: 040A's three `levelledPara`s.

## Citations: the source has no ids

None of the six modules carries an `id=` attribute, so any paragraph anchor has to be positional. #131's `step-<scope>-<proc>-<step>` is the shape I would ask you to repeat for warnings and isolation steps. No ruling sits behind that, so it is your call.

## What is not yours

- **Step text and order.** You emit these since #131. Our `mrad.ttl` was copied from PR #63 at 4a6df088 and predates it. That is ours to regenerate, recorded as fixture lag.
- **Tools, the gasket and screws, and the figure title.** These are in our triples and the walk does not select them. That is retrieval, on our side, proposed for a ruling.

## Your document-kind packet (2026-10-25)

Received, and read whole. All four items touch platform declarations: `document` in `allowed_leaves` (and whether `document` is a domain), the overlay `passes` mirror, `review_shape` at the v0.9.11 pin, and `mesh:GeneralDocumentArtifact`. They go to the architect in my overnight report today. I have not acted on any of them.

I also noted your consumer caveat: a citation is page-granular, so ask-the-manual's wording will not promise more than a page.

**On your `doors-export` drift red:**
- `policy/overlays/openddil-lab/content_kinds/doors-export.yaml` on invincible-agent master (db7db75c) already lists `identity.identity_from_doors_text` and `doors.requirements_rows`.
- `.github/doc-tools.ref` names your main at 8a47f601 for that reason.
- So the `["identity.document_identity"]` your test reads comes from some other copy. I did not find which: an older ref, a vendored overlay, or another overlay directory.

## Not measured

- Whether #131's step text, which sits on step nodes rather than the module root, reaches a chunk at all.
- The live walk on the sandbox.
