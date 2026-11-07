"""Run doc-tools' process_document_artifact_job by hand inside the sandbox pod.

    cd /app && PYTHONPATH=/app /opt/venv/bin/python /tmp/tr_run/tr_run_by_hand.py \
        --expect <sha> [--dry] <s3_key> [<s3_key> ...]

Runs the IMAGE's code (/app), never a candidate tree: the pod runs its image,
and what this records is what that image writes. Keys are bucket-relative
(e.g. training/course/hydraulics-fixture/deck.pptx). Run records are appended
to $TR_RUNS (default /tmp/tr_run/runs.jsonl). --dry checks every guard and
prints the keys, then executes nothing.
Prints no secret values; env is only reported as DOC_TOOLS_* / model names.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

APP = "/app"
BUCKET = "processing-artifacts"
PARTITIONS = "pdf_files"          # document_parser partition_name (definitions.py)
JOB = "process_document_artifact_job"   # f"{component.name}_job" (document_parser.py)
OP = "process_document_artifact"        # asset/op name; config class S3FileConfig(file_url)
RUNS = os.getenv("TR_RUNS", "/tmp/tr_run/runs.jsonl")
# The training kind's prompts (plugins/training.py fallback_file). A missing one
# fails every LLM pass, is logged, and the run still reports success.
PROMPTS = ["prompts/core_instructions.md", "prompts/training_section_instructions.md"]
REPORTED_ENV = ["DOC_TOOLS_VERSION", "DOC_TOOLS_IMAGE", "LLM_MODEL", "LLM_EMBED_MODEL",
                "PROMPT_SOURCE", "TRAINING_CONCEPT_ALIGNMENT"]


def say(*a):
    print(*a, flush=True)


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def guards(expect):
    """Every reason not to run, as a list; empty means go."""
    bad = []
    import doc_tools
    say("doc_tools.__file__ =", doc_tools.__file__)
    if not os.path.abspath(doc_tools.__file__).startswith(APP + "/"):
        bad.append(f"doc_tools is not imported from {APP} - set PYTHONPATH={APP}")
    if os.path.realpath(os.getcwd()) != os.path.realpath(APP):
        bad.append(f"cwd is not {APP} (prompts/ resolves against the cwd)")
    for p in PROMPTS:
        if not os.path.isfile(p):
            bad.append(f"missing {p} under the cwd")
    ver = os.getenv("DOC_TOOLS_VERSION") or ""
    if len(expect) < 7 or not ver or not (ver.startswith(expect) or expect.startswith(ver)):
        bad.append(f"DOC_TOOLS_VERSION={ver!r} is not --expect {expect!r}")
    mode = os.getenv("TRAINING_CONCEPT_ALIGNMENT", "dry").strip().lower()
    if mode != "dry":
        bad.append(f"TRAINING_CONCEPT_ALIGNMENT={mode!r}; this runner writes dry only")
    return bad


def _alignment_meta(res):
    """The concept_alignment output metadata build_knowledge_graph records."""
    out = {}
    for ev in res.get_asset_materialization_events():
        md = getattr(ev.event_specific_data.materialization, "metadata", None) or {}
        for k in ("concept_alignment", "concept_alignment_summary"):
            if k in md:
                v = md[k]
                out[k] = str(getattr(v, "value", getattr(v, "text", v)))
    return out


def main(argv):
    dry = "--dry" in argv
    argv = [a for a in argv if a != "--dry"]
    if len(argv) < 3 or argv[0] != "--expect":
        say("usage: tr_run_by_hand.py --expect <sha> [--dry] <s3_key> [...]")
        return 2
    expect, keys = argv[1], argv[2:]
    bad = guards(expect)
    for b in bad:
        say("ABORT:", b)
    if bad:
        return 2
    say("guards ok;", len(keys), "keys; runs ->", RUNS, "; env",
        {k: os.getenv(k) for k in ("DOC_TOOLS_VERSION", "TRAINING_CONCEPT_ALIGNMENT")})
    if dry:
        for key in keys:
            say("DRY", key)
        return 0

    from dagster import DagsterInstance
    from doc_tools.definitions import defs

    job = defs.get_job_def(JOB)
    instance = DagsterInstance.ephemeral()
    rc = 0
    for key in keys:
        pk = key.replace("/", "__")
        rec = {"key": key, "partition_key": pk, "success": False, "failed_steps": [],
               **{k: os.getenv(k) for k in REPORTED_ENV}, "expect": expect}
        t0 = time.time()
        rec["start_utc"] = _iso(t0)
        try:
            instance.add_dynamic_partitions(PARTITIONS, [pk])
            res = job.execute_in_process(
                run_config={"ops": {OP: {"config": {"file_url": f"s3://{BUCKET}/{key}"}}}},
                partition_key=pk, instance=instance, raise_on_error=False)
            rec["success"] = bool(res.success)
            rec.update(_alignment_meta(res))
            for ev in res.get_step_failure_events():
                err = getattr(ev.event_specific_data, "error", None)
                msg = ""
                if err is not None:
                    msg = f"{getattr(err, 'cls_name', '')}: {getattr(err, 'message', '')}"
                rec["failed_steps"].append({"step": ev.step_key, "error": msg[:2000]})
        except Exception as e:  # harness-level failure; keep going
            rec["failed_steps"].append({"step": "<harness>", "error": f"{type(e).__name__}: {e}"[:2000]})
        t1 = time.time()
        rec["end_utc"] = _iso(t1)
        rec["wall_seconds"] = round(t1 - t0, 2)
        with open(RUNS, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        say(f"{'OK  ' if rec['success'] else 'FAIL'} {key} wall={rec['wall_seconds']}s "
            f"alignment={rec.get('concept_alignment')} failed={[s['step'] for s in rec['failed_steps']]}")
        if not rec["success"]:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
