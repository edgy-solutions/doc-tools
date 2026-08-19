"""Reproduce (and A/B-fix) manufacturing WI under-extraction against a local LLM.

Self-contained: standard library only (urllib), so it runs without the project
venv. It deliberately mirrors the PRODUCTION request shape without importing
BAML:
  * the system prompt is the real prompts/manufacturing_instructions.md
    (with the procedure_id / step_id regexes substituted, like the plugin),
  * the output schema mirrors baml_src/manufacturing.baml ManufacturingStep,
    INCLUDING the current figure_references description (which contradicts the
    prompt's [FIGURE: <file>] rule) so the figures-come-back-empty bug reproduces,
  * the whole thing is sent as ONE system message (BAML's default role), exactly
    as ExtractWorkInstructions does.

It then scores extracted steps / figures / operations against the fixture's
ground truth, for each assembly variant, so we can see the under-extraction and
measure whether a fix moves the needle.

Usage (PowerShell):
  $py = "C:\\Users\\cnogr\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"
  & $py scripts/repro_manufacturing_extraction.py `
      --base-url http://192.168.1.126:11434/v1 --model gpt-oss-128k:120b `
      --assembler both

Flags:
  --assembler current|structured|both   which text assembly to feed the model
  --fix-figure-desc                      use the corrected figure_references
                                         description (sanctions [FIGURE: file])
  --max-tokens N                         cap output (default: none / model default)
  --dump-prompt                          print the assembled document text & exit
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX_DIR = os.path.join(ROOT, "tests", "fixtures", "manufacturing")

PROC_FMT = r"^\d{4}$"
STEP_FMT = r"^\d+(?:\.\d+)*$"

# The CURRENT figure_references description, copied verbatim from
# baml_src/manufacturing.baml — note it says "extract the identifier only
# (e.g. '3','12A')" and never mentions the [FIGURE: <file>] placeholders, which
# contradicts prompts/manufacturing_instructions.md.
FIG_DESC_CURRENT = (
    "Extract ONLY explicit figure, image, graphic, or drawing identifiers "
    "referenced in this step. Valid examples: 'Figure 3', 'Fig. 12A', 'Graphic "
    "7', 'Drawing 101-B'. Extract the identifier only (e.g., '3', '12A', '7', "
    "'101-B'). Do NOT extract vague references like 'see the diagram below'. "
    "Return empty array if no explicit figure ID is present."
)
# A corrected description that ALSO sanctions the resolvable crop placeholders.
FIG_DESC_FIXED = (
    "Extract figure references for THIS step. TWO forms both count: (1) prose "
    "callouts the document makes ('Figure 3', 'Fig. 12A') — return the "
    "identifier ('3','12A'); and (2) inline [FIGURE: <filename>] placeholders "
    "(e.g. [FIGURE: figure-4-5.jpg]) that sit within or adjacent to this step — "
    "return the <filename> VERBATIM (e.g. 'figure-4-5.jpg'), do not renumber or "
    "strip the extension. Return an empty array only if neither is present."
)


def load_fixture(stem="synthetic_work_instruction"):
    with open(os.path.join(FIX_DIR, f"{stem}.json"), encoding="utf-8") as f:
        els = json.load(f)
    with open(os.path.join(FIX_DIR, f"{stem}.groundtruth.json"), encoding="utf-8") as f:
        gt = json.load(f)
    return els, gt


# --------------------------------------------------------------------------- #
# Assembly variants
# --------------------------------------------------------------------------- #
def _figure_md(el):
    ip = (el.get("metadata") or {}).get("image_path")
    name = os.path.basename(ip) if ip else ""
    marker = f"[FIGURE: {name}]" if name else "[FIGURE]"
    cap = (el.get("text") or "").strip()
    return f"{marker}\n{cap}" if cap else marker


def _table_md(el):
    # Mirror formatters.convert_element_to_markdown's hybrid block without pandas.
    html = (el.get("metadata") or {}).get("text_as_html") or ""
    return (f"### TABLE STRUCTURE (SPATIAL) ###\n{html if html else 'Structure unavailable'}\n\n"
            f"### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###\n{el.get('text','')}")


def assemble_current(els):
    """Today's path: convert each element to markdown, join with blank lines.
    No page markers, no type labels, header/footer furniture inlined as text."""
    parts = []
    for el in els:
        t = el.get("type")
        if t in ("Image", "Figure"):
            parts.append(_figure_md(el))
        elif t == "Table":
            parts.append(_table_md(el))
        else:
            parts.append(el.get("text", ""))
    return "\n\n".join(parts)


def assemble_structured(els):
    """Proposed path: page delimiters, type tags, header/footer furniture
    collapsed to a single labeled line per page, tables/figures preserved."""
    out = []
    cur_page = None
    for el in els:
        page = (el.get("metadata") or {}).get("page_number")
        if page != cur_page:
            out.append(f"\n===== PAGE {page} =====")
            cur_page = page
        t = el.get("type")
        if t in ("Header", "Footer"):
            # Page furniture: keep ONE compact labeled line, don't repeat the block.
            out.append(f"[{t}] {el.get('text','')}")
        elif t in ("Image", "Figure"):
            out.append(_figure_md(el))
        elif t == "Table":
            out.append(_table_md(el))
        elif t == "Title":
            out.append(f"## {el.get('text','')}")
        elif t == "ListItem":
            out.append(f"- {el.get('text','')}")
        else:
            out.append(el.get("text", ""))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Prompt / schema (mirrors ExtractWorkInstructions)
# --------------------------------------------------------------------------- #
# Base per-step fields (mirrors baml_src/manufacturing.baml ManufacturingStep),
# as (name, json-type-hint) in schema order. figure_references is last, then the
# overlay fields get appended after it (TypeBuilder appends onto @@dynamic).
BASE_FIELDS = [
    ("procedure_id", f'"string, must match {PROC_FMT}"'),
    ("step_id", f'"string, must match {STEP_FMT}"'),
    ("instruction_text", '"string — the full verbatim text of the step"'),
    ("action_verb", '"string"'),
    ("tooling", '["string"]'),
    ("consumables", '["string"]'),
    ("hazard_class", '"string or null"'),
    ("required_cert", '"string or null"'),
    ("standard_ref", '"string or null"'),
    ("is_value_added", "true"),
    ("is_safety_critical", "false"),
    ("process_category", '"string"'),
    ("justification", '"string, one sentence"'),
    ("estimated_duration_minutes", "null"),
    ("military_and_industry_standards", '["string"]'),
    ("internal_part_numbers", '["string"]'),
    ("material_and_hardware_slang", '["string"]'),
    ("figure_references", None),  # description filled from fig_desc at build time
]

# Simulated proprietary overlay fields (MANUFACTURING_OVERLAY_SPEC). Names/shapes
# are invented but plausible; several ARE derivable from the doc, several are not
# — mirroring the real "most come back empty" behaviour.
OVERLAY_POOL = [
    ("work_center", '"string or null — recommended work center / station"'),
    ("labor_category", '"string or null — skill level / labor category required"'),
    ("inspection_method", '"string or null — Visual | Dimensional | Functional | NDI"'),
    ("calibration_ref", '"string or null — calibration standard or gage ID referenced"'),
    ("torque_value", '"string or null — torque value with units if specified"'),
    ("cure_time_minutes", "null // int or null — cure/dwell time in minutes if stated"),
    ("ppe_required", '["string"] // personal protective equipment required'),
    ("quality_clause", '"string or null — quality clause / acceptance criteria ref"'),
    ("lot_traceability_required", "false // true if lot/serial traceability required"),
    ("first_article_required", "false // true if first-article inspection applies"),
    ("rework_disposition", '"string or null — rework/disposition instruction if any"'),
    ("environmental_control", '"string or null — ESD/temp/humidity control required"'),
    ("record_field", '"string or null — value the operator must record (e.g. cure time)"'),
    ("witness_point", "false // true if this is a witness / hold point"),
    ("consumable_shelf_life", '"string or null — shelf-life/expiration for a consumable"'),
]


def step_field_names(n_overlay):
    return [n for n, _ in BASE_FIELDS] + [n for n, _ in OVERLAY_POOL[:n_overlay]]


def build_system_prompt(fig_desc, n_overlay=0):
    with open(os.path.join(ROOT, "prompts", "manufacturing_instructions.md"), encoding="utf-8") as f:
        instr = f.read()
    instr = instr.replace("{{ procedure_id_format }}", PROC_FMT).replace(
        "{{ step_id_format }}", STEP_FMT)
    lines = []
    for name, hint in BASE_FIELDS:
        if name == "figure_references":
            lines.append(f'      "figure_references": ["string"]  // {fig_desc}')
        else:
            lines.append(f'      "{name}": {hint},')
    for name, hint in OVERLAY_POOL[:n_overlay]:
        lines.append(f'      "{name}": {hint},')
    # trailing comma cleanup: ensure the last line has no dangling comma
    if lines and lines[-1].rstrip().endswith(","):
        lines[-1] = lines[-1].rstrip()[:-1]
    step_obj = "\n".join(lines)
    schema = f"""
### OUTPUT FORMAT ###
Answer with ONLY a JSON object of this shape (no prose, no code fences):
{{
  "steps": [
    {{
{step_obj}
    }}
  ],
  "assessment": {{ "proprietary_score": 0.0, "outsourceable": false }}
}}
Extract EVERY discrete step in the document. Fill in EVERY field for EVERY step
when the information is present; use null / empty array only when it is genuinely
absent. Do not summarize or omit steps."""
    return instr + "\n" + schema


def call_llm(base_url, model, system_prompt, document_text, max_tokens, timeout):
    body = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": f"{system_prompt}\n\n### DOCUMENT TEXT ###\n---\n{document_text}\n---"},
            {"role": "user", "content": "Extract now. Return only the JSON object."},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer any"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    dt = time.time() - t0
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage, dt


def parse_steps(content):
    """Robustly pull the JSON object out of the model content."""
    txt = content.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", txt).strip()
    # find the outermost {...}
    start = txt.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(txt)):
        if txt[i] == "{":
            depth += 1
        elif txt[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(txt[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


_FILENAME_RE = re.compile(r"figure-\d+-\d+\.jpg$", re.I)


def score(parsed, gt):
    steps = (parsed or {}).get("steps") or []
    n_steps = len(steps)
    procs = sorted({(s.get("procedure_id") or "").strip() for s in steps if s.get("procedure_id")})
    steps_with_fig = [s for s in steps if s.get("figure_references")]
    all_refs = [str(r) for s in steps for r in (s.get("figure_references") or [])]
    resolvable = [r for r in all_refs if _FILENAME_RE.search(r)]   # figure-4-5.jpg form
    return {
        "n_steps": n_steps, "gt_steps": gt["n_steps"],
        "n_operations": len(procs), "gt_operations": gt["n_operations"], "operations": procs,
        "steps_with_figures": len(steps_with_fig),
        "total_figure_refs": len(all_refs), "gt_figures": gt["n_figures"],
        "all_refs": all_refs, "resolvable_refs": resolvable,
        "n_resolvable": len(set(resolvable)), "gt_figure_files": gt["figure_files"],
    }


def _filled(v):
    """A field counts as 'filled' if it carries real content."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, bool):
        return v  # a bool 'filled' only when True (False reads as 'not flagged')
    return True


def field_report(parsed, field_names):
    steps = (parsed or {}).get("steps") or []
    n = len(steps) or 1
    rows = []
    for f in field_names:
        filled = sum(1 for s in steps if _filled(s.get(f)))
        rows.append((f, filled, len(steps), filled / n))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", "http://192.168.1.126:11434/v1"))
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt-oss-128k:120b"))
    ap.add_argument("--assembler", choices=["current", "structured", "both"], default="both")
    ap.add_argument("--fix-figure-desc", action="store_true")
    ap.add_argument("--overlay-fields", type=int, default=0,
                    help="inject N simulated proprietary overlay fields into the schema")
    ap.add_argument("--max-tokens", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--dump-prompt", action="store_true")
    ap.add_argument("--fixture", default="synthetic_work_instruction",
                    help="fixture stem: synthetic_work_instruction | synthetic_work_instruction_hard")
    args = ap.parse_args()

    els, gt = load_fixture(args.fixture)
    variants = ["current", "structured"] if args.assembler == "both" else [args.assembler]
    assemblers = {"current": assemble_current, "structured": assemble_structured}

    if args.dump_prompt:
        for v in variants:
            text = assemblers[v](els)
            print(f"\n{'='*30} ASSEMBLY: {v}  ({len(text)} chars) {'='*30}\n")
            print(text)
        return

    fig_desc = FIG_DESC_FIXED if args.fix_figure_desc else FIG_DESC_CURRENT
    system_prompt = build_system_prompt(fig_desc, args.overlay_fields)
    field_names = step_field_names(args.overlay_fields)
    print(f"Model: {args.model}   Endpoint: {args.base_url}")
    print(f"Figure description: {'FIXED' if args.fix_figure_desc else 'CURRENT (contradicts prompt)'}")
    print(f"Overlay fields injected: {args.overlay_fields}  (schema has "
          f"{len(field_names)} per-step fields)")
    print(f"Ground truth: {gt['n_steps']} steps, {gt['n_operations']} operations "
          f"{gt['operations']}, {gt['n_figures']} figures\n")

    for v in variants:
        text = assemblers[v](els)
        print(f"--- assembler={v}  ({len(text)} chars) ---")
        try:
            content, usage, dt = call_llm(args.base_url, args.model, system_prompt,
                                          text, args.max_tokens, args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"  REQUEST FAILED: {e}\n")
            continue
        # Save the raw response so we never have to re-run a 5-min call to inspect.
        tag = f"{v}_{'fixed' if args.fix_figure_desc else 'current'}"
        outp = os.path.join(FIX_DIR, f"_repro_response_{tag}.json")
        with open(outp, "w", encoding="utf-8") as f:
            f.write(content)
        parsed = parse_steps(content)
        if parsed is None:
            print(f"  Could not parse JSON from response ({len(content)} chars). "
                  f"First 300 chars:\n  {content[:300]}\n  (raw saved to {outp})\n")
            continue
        sc = score(parsed, gt)
        print(f"  tokens: in={usage.get('prompt_tokens','?')} out={usage.get('completion_tokens','?')}  "
              f"time={dt:.0f}s   (raw saved to {os.path.basename(outp)})")
        print(f"  steps extracted : {sc['n_steps']}/{sc['gt_steps']}")
        print(f"  operations      : {sc['n_operations']}/{sc['gt_operations']}  {sc['operations']}")
        print(f"  steps w/ figures: {sc['steps_with_figures']}   total figure refs: "
              f"{sc['total_figure_refs']}  (doc has {sc['gt_figures']} figures)")
        print(f"  RESOLVABLE (figure-*.jpg): {sc['n_resolvable']}/{sc['gt_figures']}")
        print(f"  actual figure_references values: {sc['all_refs']}")
        print(f"  doc's real figure files       : {sc['gt_figure_files']}")
        print("  --- per-field fill rate across steps (emptiest first) ---")
        for f, filled, total, rate in sorted(field_report(parsed, field_names), key=lambda r: r[3]):
            bar = "#" * int(round(rate * 20))
            print(f"    {f:34s} {filled:2d}/{total:<2d} {rate*100:5.0f}%  {bar}")
        print()


if __name__ == "__main__":
    sys.exit(main())
