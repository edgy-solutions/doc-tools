"""Run doc-tools' process_document_artifact_job by hand inside the sandbox pod.

    PYTHONPATH=/tmp/cand_tr:/app /opt/venv/bin/python /tmp/cand_tr/tr_run_by_hand.py <s3_key> [<s3_key> ...]

Keys are bucket-relative (e.g. training/course/hydraulics-fixture/deck.pptx).
Prints no secret values; env is only reported as DOC_TOOLS_* / model names.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

CAND = "/tmp/cand_tr"
BUCKET = "processing-artifacts"
PARTITIONS = "pdf_files"          # document_parser partition_name (definitions.py)
JOB = "process_document_artifact_job"   # f"{component.name}_job" (document_parser.py)
OP = "process_document_artifact"        # asset/op name; config class S3FileConfig(file_url)
RUNS = os.path.join(CAND, "runs.jsonl")


def say(*a):
    print(*a, flush=True)


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def main(keys):
    import doc_tools
    say("doc_tools.__file__ =", doc_tools.__file__)
    if not os.path.abspath(doc_tools.__file__).startswith(CAND):
        say("ABORT: doc_tools is not imported from", CAND, "- fix PYTHONPATH")
        return 2
    # Prompt files resolve against the cwd ("prompts/core_instructions.md"). From
    # any other directory every LLM pass fails, is logged, and the run still
    # reports success with zero concepts.
    if os.path.realpath(os.getcwd()) != os.path.realpath(CAND):
        say("ABORT: run from", CAND, "(prompts/ resolves against the cwd)")
        return 2
    if not keys:
        say("usage: tr_run_by_hand.py <s3_key> [...]")
        return 2

    from dagster import DagsterInstance
    from doc_tools.definitions import defs

    job = defs.get_job_def(JOB)
    sha = _read(os.path.join(CAND, "CANDIDATE_SHA"))
    instance = DagsterInstance.ephemeral()
    rc = 0
    for key in keys:
        pk = key.replace("/", "__")
        rec = {"key": key, "partition_key": pk, "success": False, "failed_steps": [],
               "DOC_TOOLS_VERSION": os.getenv("DOC_TOOLS_VERSION"),
               "DOC_TOOLS_IMAGE": os.getenv("DOC_TOOLS_IMAGE"),
               "LLM_MODEL": os.getenv("LLM_MODEL"),
               "LLM_EMBED_MODEL": os.getenv("LLM_EMBED_MODEL"),
               "candidate_sha": sha}
        t0 = time.time()
        rec["start_utc"] = _iso(t0)
        try:
            instance.add_dynamic_partitions(PARTITIONS, [pk])
            res = job.execute_in_process(
                run_config={"ops": {OP: {"config": {"file_url": f"s3://{BUCKET}/{key}"}}}},
                partition_key=pk, instance=instance, raise_on_error=False)
            rec["success"] = bool(res.success)
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
            f"failed={[s['step'] for s in rec['failed_steps']]}")
        if not rec["success"]:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
