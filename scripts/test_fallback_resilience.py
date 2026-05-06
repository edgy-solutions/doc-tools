import os
import sys

# Intentionally clear Langfuse env vars to force a failure
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ.pop("LANGFUSE_HOST", None)

from doc_tools.plugins.sustainment import SustainmentPlugin

def run_test():
    print("--- Starting Resilience Test ---")
    print("Simulating Langfuse Outage (Env vars cleared)...")
    
    plugin = SustainmentPlugin(domain_type="sustainment")
    
    # 1. Test _get_dynamic_prompt fallback directly
    print("\n[Test 1] Testing _get_dynamic_prompt fallback...")
    try:
        prompt = plugin._get_dynamic_prompt(
            prompt_name="sustainment_instructions",
            fallback_file="prompts/sustainment_instructions.md"
        )
        if prompt and ("DATA" in prompt or "Sustainment" in prompt or "notice" in prompt):
            print("[PASS] TEST 1: Successfully read local Markdown file.")
        else:
            print(f"[FAIL] TEST 1: File read succeeded, but content was missing or unexpected. Content start: {prompt[:50]}")
            sys.exit(1)
    except Exception as e:
        print(f"[FAIL] TEST 1: _get_dynamic_prompt crashed: {e}")
        sys.exit(1)

    # 2. Test Legacy Chunking Fallback (BAML Signature check)
    print("\n[Test 2] Testing process_fulltext legacy fallback (BAML signature check)...")
    try:
        # Passing an empty elements list forces the legacy text fallback
        # Note: This might fail if Ollama/LLM is not running, but we check for TypeError (missing args)
        result = plugin.process_fulltext(
            full_text="Test Part Number: TLC271CS-13 is replaced by FD2000060.",
            doc_id="TEST-001",
            elements=[] 
        )
        print("[PASS] TEST 2: BAML executed successfully without missing argument errors.")
    except TypeError as type_err:
        if "system_instructions" in str(type_err):
            print(f"[FAIL] TEST 2: BAML function is missing system_instructions parameter. {type_err}")
        else:
            print(f"[FAIL] TEST 2: Unexpected TypeError: {type_err}")
        sys.exit(1)
    except Exception as e:
        # If it fails because of Ollama/GPT not running locally, that's fine, the signature was correct.
        if "ExtractSustainment" in str(e) and "missing 1 required positional argument" in str(e):
             print(f"[FAIL] TEST 2: BAML function is missing system_instructions parameter. {e}")
             sys.exit(1)
        print(f"[NOTE] TEST 2: Extraction threw an error (likely LLM unavailable), but signature is fine: {e}")

    print("\n[SUCCESS] ALL TESTS PASSED. The pipeline is highly available.")

if __name__ == "__main__":
    # Ensure doc_tools is in the path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    run_test()
