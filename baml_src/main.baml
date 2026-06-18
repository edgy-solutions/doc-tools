generator target {
  output_type "python/pydantic"
  output_dir "../doc_tools"
  version "0.222.0"
}

// Global LLM client — generic OpenAI-compatible.
//
// The "openai-generic" provider speaks the OpenAI Chat Completions wire
// protocol against any backend that implements it. Concretely covers:
//   - Ollama        (direct, /v1 endpoint)
//   - LiteLLM       (proxy at /v1, fronts Ollama / vLLM / OpenRouter / real
//                    OpenAI; the iagent helm chart deploys it optionally)
//   - vLLM          (direct, /v1 endpoint; vLLM's max_model_len is fixed
//                    at server start, so the LLM_NUM_CTX option below is
//                    silently dropped on the vLLM path — managed by the
//                    vLLM deployment, not per-request)
//   - OpenAI / OpenRouter (with a real key in LLM_API_KEY)
//
// LLM_API_KEY may be empty for direct Ollama (it ignores the header) or
// LiteLLM in stateless mode (any non-empty token accepted). Real OpenAI
// and OpenRouter require a real key. Defaults to "any" in the chart values
// — works for the first two cases and explicitly opt-in for the latter.
//
// LLM_NUM_CTX is an Ollama-specific extra option. LiteLLM passes it through
// when the downstream is Ollama; vLLM and real OpenAI ignore it. Set it for
// Ollama backends; leave default for the rest.
client<llm> LLM {
  provider "openai-generic"
  options {
    base_url env.LLM_BASE_URL
    api_key env.LLM_API_KEY
    model env.LLM_MODEL
    options: {
      num_ctx: env.LLM_NUM_CTX
    }
  }
}
