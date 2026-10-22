# What doc-tools is actually running, and everything that is not

to: invincible-agent/seat/architect (cc Chris)
from: doc-tools/lane/7f
date: 2026-10-22

Read off the cluster and the tree. **No rolls; the freeze holds.** Every digest
below is a pod `imageID`, never a values file and never the pod's `image` field
(that one shows the local config digest `sha256:ac698376...`, which is not the
code identity).

## 1. Live on the sandbox

| | |
| --- | --- |
| cluster / ns | context `edge` (cluster `edge-direct`), namespace `sandbox` |
| pod | `doc-tools-557cc96c6b-7v2z2`, Running 1/1, started **2026-10-18 03:51:41Z** |
| **digest (imageID)** | `ghcr.io/edgy-solutions/doc-tools@sha256:ac853308f4b176ea5ac40aaa6fff1d88e9669a07a2af7a554afa41e3c8e98ed5` |
| the gate pods agree | the latest CronJob pod carries the same `imageID` |
| helm | release `doc-tools` **revision 53**, chart `doc-tools-0.1.5`, deployed 2026-10-18 03:53:42Z |
| **the code in it** | the image built from `133714c` — **PR #141**, "Seal the zero-row review POST, and serve the notice id from extraction only" |
| **the PR that pinned it** | **PR #143** (merge `c2a22cf`), "Roll the sandbox pin to ac853308..." |

Two things in that row are worth saying out loud:

- **The roll preceded the chart commit by ~23 hours.** #141 merged 2026-10-18
  02:29Z; the pod started 03:51Z; #143 — the commit that writes this digest into
  `values-sandbox.yaml:1136` — merged 2026-10-19 02:39Z. Helm read the working
  tree, which is how pins land on this lane. The tree and the cluster agree
  *now*: chart digest == pod imageID == `expectImage` (`:1422`).
- Revisions 52 and 53 are two minutes apart and the pod only restarted for 52.
  53 moved `corpusGate.expectImage` alone, deliberately, so the gate would not
  compare the file against itself.

Also live, unasked but relevant: of the six gate CronJob pods still on the node,
**three are in `Error`** (ages 6d8h, 4d9h, 3d9h) and the three most recent
Completed.

## 2. Merged to main since that pin, and not rolled

Exactly **one** commit. `origin/main` head is `809963c`.

| commit / PR | what it touches | affects a PCN drop -> review -> promote? |
| --- | --- | --- |
| `809963c` — **#144** "Land the authority report at the declared pin, and make the verdict assert only when applicable" | 4 `docs/corpus-gate/report-*.md`, `docs/corpus-gate/latest.json`, `tests/test_corpus_gate_guard.py` | **No.** No file in it ships in the image. Rolling it would change nothing in the pod. It changes the gate's authority report and a guard test only. |

So: **the sandbox is one docs-only merge behind main.** There is no unrolled code
on main at all.

## 3. Open PRs, not merged

All ten are based on `main`, so CI applies to each (none is stacked).

| PR | branch | what it touches | affects drop -> review -> promote? |
| --- | --- | --- | --- |
| **#145** | `7f/idt-per-row-word-bboxes` | `plugins/sustainment.py`, `utils/sustainment_merge.py`, `utils/table_text_layer.py` + 2 suites | **Yes — review.** Puts a per-row bbox on vision part rows from the PDF word layer, so a review row gains its `evidence_ref`. |
| **#102** | `feat/jena-writer-under-rulings` | `assets/semantic_assets.py`, 6 plugins incl. `sustainment.py`, `utils/jena_client.py`, 4 suites, 1 golden | **Yes — promote.** This is the graph write itself, routed through the SDK writer under the three rulings. |
| **#28** | `lane/7f-jena-ontology-writer` | the same set, plus `pyproject.toml`, minus `test_jena_writer_identity_and_subject.py` | **Yes — promote, and it is the older cut of #102.** Two open PRs for one piece of work; one should be closed. |
| **#99** | `feat/cad-kinds` | `passes/cad.py`, `utils/content_kind.py`, `registry/content_kind_domains.json`, 2 kind YAMLs, 4 fixtures, 1 suite | **Not PCN** — but it edits the shared router `content_kind.py`, so it is not inert for a PCN drop either. Worth a read before merge, not a block. |
| **#100** | `feat/doors-requirements-rows` | `parsers/doors_export.py`, `utils/content_kind.py`, `registry/content_kinds/doors-export.yaml`, 3 suites | **Not PCN**, same shared-router caveat as #99. |
| **#125** | `fix/kinds-docstring-triple-count-attribution` | `api/kinds.py` — **one hunk, entirely inside the module docstring** — plus a session report | **No.** Corrects the "8 triples to Jena" attribution. No runtime behaviour. |
| **#110** | `corpus-gate/nightly` | 4 nightly `docs/corpus-gate/report-*.md` + `latest.json` | **No.** Reports only. `gh` currently answers `MERGEABLE` for it. |
| **#33** | `pcn/reingest-backup-per-notice` | `docs/pcn-reingest-runbook.md` | **No.** Runbook. |
| **#64** | `chore/claude-md-venv-pytest` | `CLAUDE.md` | **No.** |
| **#73** | `chore/pin-sandbox-877677c` | `charts/doc-tools/values-sandbox.yaml` | **Yes, destructively — this one should be closed.** Opened 2026-10-06. It sets `digest` to `sha256:1f1e1680...` against a base of `sha256:b54d9ef2...`, both long superseded. Merging it now moves the sandbox pin **backwards** off `ac853308`. |

## 4. On a branch, no PR

`origin` carries **41 branches unmerged to main**. Most are spent pin/chore
branches. The ones that hold work:

| branch | ahead of main | code it touches | affects drop -> review -> promote? |
| --- | --- | --- | --- |
| **local `HEAD` (not pushed)** | **43** — 19 of them exist nowhere but this laptop | incl. `utils/table_text_layer.py`, `prompts/sustainment_grid_columns_instructions.md`, `utils/sustainment_merge.py`, `utils/leaf_read.py`, `utils/provenance.py`, `utils/content_kind.py`, `assets/semantic_assets.py` | **Yes — drop (extraction).** This is the HEMCG2-2683 pairing fix (`e94c06b`) and the grid-column prompt (`fbc9932`), plus the leaf/provenance work. **Flagging the real risk here: the newest 19 commits are unpushed, so nothing but this machine has them.** |
| `7f/report-2026-10-19-required-gate-red-on-age` | 24 | the pushed part of the above | Yes — drop. No PR open. |
| `mfg-extraction-investigation` | **30** | `utils/mfg_extractors.py` + 4 `scripts/` | Not the PCN path (manufacturing). 30 commits, no PR — known backlog. |
| `mesh/ingress-user-stamp` | 8 | `assets/semantic_assets.py`, `components/document_parser.py`, `definitions.py`, `partitions.py`, `plugins/sustainment.py`, `utils/{dagster_resources,ingest_id,ingest_provenance}.py` | **Yes — drop.** It is in the ingest identity path and in the sustainment plugin. Largest unreviewed code surface of anything here. |
| `pcn/grid-no-parts-column` | 1 | `baml_src/sustainment.baml`, `plugins/sustainment.py`, **`prompts/sustainment_grid_columns_instructions.md`**, 3 generated `baml_client` files | **Yes — drop.** And note: it edits **the same prompt file** my unpushed `fbc9932` edits. Whichever lands second has to merge by hand. |
| `fix/sustainment-empty-crops` | 1 | `plugins/sustainment.py` | Yes — drop (the crop path). |
| `feat/kind-registry-and-provenance-invariant` | 1 | 12 code/registry files | Routing + provenance; shared with the PCN path. |
| `feat/xml-instance-graph-write` | 1 | `assets/{semantic_assets,xml_ingestion}.py`, `utils/content_kind.py` | Promote, **XML not PCN** (the urn:doc-only write). |
| `7f/dmc-keyed-supersede` | 2 | `assets/{semantic_assets,xml_ingestion}.py` | S1000D supersede, not PCN. |
| `7f/honest-corpus-gate-verdict`, `pcn/gate-per-notice-and-log-preservation`, `chore/gate-{expect-image,void-on-image-mismatch}`, `pcn/dotted-revision-order`, `chore/kind-domain-optional`, `lane/7f`, `docs/agents-pdn-handoff-pointers`, `lane/01-sor-placeholder`, `chore/sor-placeholder` | 1-9 each | gate instruments, docs, placeholders | No, for a drop. Gate-verdict only. |
| ~20 `chore/pin-*`, `pcn/pin-*`, `pin/*` branches | 1-2 | the chart pin | Superseded. Each would move the pin backwards exactly like #73. |

## 5. `work` — I cannot see its pin, and here is why

**`work` is the d4 cluster and nothing in this tree or on my kubeconfig
reaches it.** Measured: my contexts are `edge`, `edge-rancher` and
`docker-desktop`; this cluster's namespaces are listed in full and there is no
`work`/`d4` namespace among them; and `charts/doc-tools/` has exactly three
values files — `values.yaml`, `values-sandbox.yaml`,
`values-sandbox.secret.yaml`. **There is no d4 values file in this repo**, so
d4's pin is not declared here and I cannot read it even indirectly.

What Chris should check there, in this order, because each can hold while the
next does not:

1. **The registry hop d4 actually uses.** d4 pulls from **Artifactory**, not
   ghcr. A green CI build and a ghcr push make code live on sandbox and do
   **nothing** for d4 — an image has to be pushed to Artifactory.
2. **`imageID`, not `image` and not the tag**, on the d4 pods — a
   `kubectl --context <d4> -n <ns> get pods -l app=doc-tools` with an
   `-o jsonpath` over `.status.containerStatuses[*].imageID`.
3. **Extraction runs in separate `dagster-run-*` pods**, so the code-server pod's
   digest does not tell you what an extraction ran. Check a recent run pod too.
4. **Where d4's values live.** If d4 is rolled from a values file, it is in
   another tree, and that file's digest is the thing to diff against step 2.
   If the answer is `:latest`, the tag hides which code is deployed and only
   `imageID` settles it.

## 6. The short version

The sandbox runs **`ac853308`** = the code from **#141**, pinned by **#143**,
and it is **one docs-only merge (#144) behind main** — so there is no unrolled
code. The real exposure is not on main: it is **43 commits of unmerged work**,
**19 of them unpushed**, including the HEMCG2-2683 extraction fix; **#145, #102,
#28, `mesh/ingress-user-stamp`, `pcn/grid-no-parts-column` and
`fix/sustainment-empty-crops` all sit on the drop -> review -> promote path**;
**#73 and ~20 pin branches would roll the sandbox backwards** if merged; and
**d4/work is invisible from here** for the reasons in §5.

— doc-tools/lane/7f
