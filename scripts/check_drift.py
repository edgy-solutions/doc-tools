import os
import sys
import glob
from langfuse import Langfuse

def check_prompt_drift():
    # The label checked here MUST match the label the runtime serves on the
    # opt-in Langfuse path (doc_tools/plugins/base.py reads the same env var),
    # otherwise CI would validate a different version than prod could serve.
    label = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    print(f"Starting Prompt Drift Detection (label='{label}')...")
    langfuse = Langfuse()
    prompt_dir = "prompts/"
    drift_found = False

    # Ensure prompts directory exists
    if not os.path.exists(prompt_dir):
        print(f"❌ ERROR: Prompt directory '{prompt_dir}' not found.")
        sys.exit(1)

    for filepath in glob.glob(os.path.join(prompt_dir, "*.md")):
        prompt_name = os.path.basename(filepath).replace(".md", "")

        with open(filepath, 'r') as file:
            local_content = file.read().strip()

        try:
            lf_prompt = langfuse.get_prompt(prompt_name, label=label)
            lf_content = lf_prompt.prompt.strip()

            if local_content != lf_content:
                print(f"❌ DRIFT DETECTED: '{prompt_name}'")
                print(f"File: {filepath} does not match the '{label}' label in Langfuse.")
                drift_found = True
            else:
                print(f"✅ IN SYNC: '{prompt_name}' matches Langfuse.")
                
        except Exception as e:
            print(f"⚠️ WARNING: Could not fetch '{prompt_name}' from Langfuse. Error: {e}")
            drift_found = True

    if drift_found:
        print("\nERROR: Please sync your Langfuse UI changes back to Git before merging.")
        sys.exit(1)
    else:
        print("\nSUCCESS: All prompts are in sync.")
        sys.exit(0)

if __name__ == "__main__":
    check_prompt_drift()
