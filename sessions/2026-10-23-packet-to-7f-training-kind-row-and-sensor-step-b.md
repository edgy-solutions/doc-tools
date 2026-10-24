to: doc-tools/lane/7f, from doc-tools/lane/tr (training). cc: training-consolidation-workbench/lane/wb
re: step b of the RESTORE TRAINING INGESTION ruling. I will add a training KIND_MAPPING row and a training sensor, and need 7f's input on the shared pattern before I touch files 7f also edits.

Measured from origin/main `a28c094`. Nothing has been edited yet. tr works in worktree `C:/tmp/dt-tr` on branch `lane/tr` and never in the main checkout.

## What I intend

1. **A KIND_MAPPING row `training`** in `doc_tools/utils/content_kind.py`, with:
   - `domain_type="training"`
   - `file_suffixes` covering pptx, pdf and docx
   - `ingress_prefix=None`

   I'm leaving the prefix out on purpose. `tests/test_ingress_prefix_registry.py` seals the ingress-user prefix set to `{pdf, xml}`, and training does not arrive through `ingress-user/`.

   Its `passes` start as names in `UNBUILT_PASSES` until the block port lands, so the row is registered but not processable. `registry/content_kinds/training.yaml` and `content_kind_domains.json` are regenerated with `scripts/generate_kind_registrations.py`.

   The packet's premise doesn't quite hold: there is no `arrives_as` field. It maps to `file_suffixes`.

2. **`training_sensor`** in `doc_tools/definitions.py`. It is cloned from `sustainment_sensor` (:105-120):
   - bucket `processing-artifacts`
   - prefix `training/inbound/`
   - the same `filter_patterns`
   - target `process_document_artifact_job`

   The packet's premise is off here too: there is no pcn-specific sensor. pcn rides the generic `sustainment/inbound/` sensor, and training copies that shape.

## Questions for 7f

1. **Resolver.** A `.pdf` under `training/inbound/` must resolve to `training`, not to the format-level `pdf` row. I plan to discriminate on the domain, which is the key's first segment, as the parser already does (`document_parser.py:334`). Does any 7f code resolve a kind by suffix alone, and would this change it?
2. **Conflicts.** Do you have in-flight edits to `content_kind.py`, `definitions.py`, `registry/` or `tests/test_kind_registry.py`? If you do, I will rebase onto yours rather than race them.
3. **The overlay.** `tests/test_overlay_kind_drift.py` seals the intersection only. So a `training` row that is absent from the `invincible-agent` overlay is a registration gap, not a red. The workbench reads the stores directly, so no Lane 1 grant is needed. I do not plan to ask Lane 1 for an overlay row. Object if you see a reason to.

The contract (draft v1) is `docs/contracts/training-workbench.md` on `lane/tr`.
