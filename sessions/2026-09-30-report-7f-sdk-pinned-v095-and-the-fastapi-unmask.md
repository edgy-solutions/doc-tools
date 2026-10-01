# Report — 7f: pinned to v0.9.5, and the bump unmasked a latent dag-tools defect

to: architect
from: doc-tools/lane/7f, 2026-09-30

---

## 0. Headline

**Re-pinned, verified against the real wheel, PR #41 open.** v0.9.5 clears *both*
of the blockers the ADR-0041 dependency map stopped on, so the ingress-user
sensor is genuinely unblocked rather than unblocked-by-assertion:

1. **The fifth rung exists.** `USER_DROP = "user-drop"` is in `OBTAINED_VIA`.
2. **The block builder is vendored into the SDK surface** —
   `ProvenanceBlock`, `make_provenance`, `validate_provenance` and
   `require_provenance` all ship in `iagent_mesh.provenance`. That is the
   "one writer, one validator" option that report asked for, not the
   re-implement-and-accept-drift option.

v0.9.5 is a **floor, not a convenience**: `provenance.py` is an *added* file in
the `v0.9.4...v0.9.5` compare. On v0.9.4 the module does not exist.

## 1. What actually moved, measured

56 commits and 40 files across the range, which says nothing on its own. The
consumed surface is what matters:

| | |
|---|---|
| `service_identity.py` (our only prior symbol, `mint_token`) | **absent from the changed-file list** — byte-identical across the bump |
| `provenance.py` | **added**, +305 lines |
| fastapi / uvicorn | **dropped from the SDK's hard deps** into a `[server]` extra (at 0.9.3) |
| `__init__.py` | +302 lines, still imports `.transport_auth` unguarded at module level |

`uv lock` confirms the net effect on doc-tools is a **removal**, not an addition:

```
Removed fastapi v0.141.1
Updated iagent-mesh v0.9.1 (557976d2) -> v0.9.5 (ceab07ac)
```

The resolved sha matches the tag I verified independently
(`ceab07ace3d10603ed06d771cf929b8150bf3158`), and the lock records the sha
alongside the tag, so a moved tag cannot silently change what builds.

## 2. The import posture is exercised, not read

The last row of that table is the shape of the **v0.9.0 breakage** that motivated
the old pin: an unguarded `from fastapi import ...` reached through
`__init__.py` made `import iagent_mesh` impossible without a web framework.
`__init__.py` grew 302 lines and *still* imports `.transport_auth` at module
level, so importability now rests entirely on the try/except inside that module.

Reading the source cannot establish that — what ships is the resolved wheel. So
the new tests were run in an ephemeral environment holding only the v0.9.5 wheel
and pytest, with fastapi **genuinely absent** (`find_spec("fastapi") is None`;
uvicorn is present only because `mcp` requires it, exactly as the SDK's own
comment predicts): **6 of 6 pass.**

## 3. One finding: the bump unmasked a latent dag-tools defect

Not caused by this change, and it does not block us, but it should be said out
loud because the masking is the interesting part.

`dag_tools` imports fastapi **unguarded at module level** in
`central_gateway/main.py` and `domain_broker/main.py`, while declaring neither
fastapi nor uvicorn in its metadata. iagent-mesh was supplying fastapi
transitively, so the undeclared dependency was invisible. Removing fastapi
removes the cover.

**Nothing here breaks.** doc-tools imports `dag_tools.utils.k8s`,
`dag_tools.components.s3_sensor.file_component` and `S3SensorComponent`;
`dag_tools/__init__.py` resolves lazily via `importlib`, and fastapi appears
nowhere else in the package. So those two server entrypoints are never reached
from this repo. But anyone who imports them after this lands gets an
`ImportError` that was always one dependency away. **Worth a packet to whoever
owns dag-tools** — it should declare what it imports.

## 4. The guard, and why it does not skip

`tests/test_mesh_sdk_pin.py`. The pin in `pyproject.toml` carries a long
*census* of the consumed surface, which is a claim about the installed package;
only a test that imports it can keep that claim true across the next bump. Six
assertions: bare import works, fastapi/uvicorn stay extras-only, `mint_token`
imports, `ProvenanceBlock` imports with `user-drop` in `OBTAINED_VIA`, a
user-drop block constructs and round-trips, an unknown rung is refused.

It deliberately **does not skip** when `iagent_mesh` is missing. It is a declared
hard dependency; a guard that skips itself into silence is how a stale claim
outlives the thing it described.

Note on `mint_token` specifically: its production import site
(`doc_tools/utils/mesh_identity.py`) sits inside a try/except that **logs and
proceeds**, so a move there would not raise in production — it would downgrade
auth quietly. That is why it gets an explicit assertion rather than relying on
the pipeline to notice.

## 5. Test state, stated plainly

**839 passed, 16 skipped, 2 xfailed.**

Three failures in the shared `.venv` are **the new guard working as designed**:
that venv still has the old 0.9.4 install, which has no
`iagent_mesh.provenance`, so the three provenance tests raise
`ModuleNotFoundError`. Against the real v0.9.5 wheel they are 6/6.

I deliberately **did not re-sync the shared venv** — other lanes have corpus
fires in flight against it, and re-resolving their environment mid-measurement
is not mine to do. CI installs from `uv.lock`, which now resolves `v0.9.5`.

## 6. What this does not do

The pin is a dependency move only, shipped **ahead of** the sensor that needs it,
so a revert can separate the dependency from the feature. No sensor, no stamp, no
deploy, no image build — the fires own the cluster and the vision host right now.

---

### State

- **PR #41** open: `pyproject.toml`, `uv.lock`, `tests/test_mesh_sdk_pin.py`.
- v0.9.5 clears both ADR-0041 blockers; `user-drop` is the fifth rung and the
  SDK is the single block writer/validator.
- fastapi is **gone** from our resolved install; nothing in doc-tools imported it.
- dag-tools has an undeclared fastapi dependency in two server entrypoints we
  never reach — flagged, not fixed here.
- Corpus fires: fire 1 scored and sealed, fire 2 running. No vision calls from
  this lane.
