# doc-tools — session rules

## Run pytest only through the venv's interpreter, from PowerShell

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/ -q > pytest.log; Get-Content pytest.log -Tail 5
```

- **Never** use `py -3`, `python` from PATH, or any other system interpreter. They load a different
  `python-magic`/libmagic pairing and block forever at import (`magic/compat.py`): no output, one
  core pegged, and the process outlives the session. On 2026-10-02 four of these had been running
  for 1–2 days and were slowing every other suite on the machine.
- **Never** run the suite from the Bash tool (git-bash) either. The same venv interpreter hangs
  in collection there and prints nothing; from PowerShell it finishes in under a minute.
- If a run produces no output, suspect the interpreter and the shell before the code. Kill it;
  don't leave it running.
- Why every module pays for this: `doc_tools/__init__.py` imports the Dagster defs, which pull
  `unstructured`, which pulls `python-magic`.
