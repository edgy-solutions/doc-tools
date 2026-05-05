generator target {
  output_type "python/pydantic"
  output_dir "../doc_tools"
  version "0.222.0"
}

// Global Clients
client<llm> Ollama {
  provider "openai-generic"
  options {
    base_url env.OLLAMA_BASE_URL
    model env.OLLAMA_MODEL
    options: {
      num_ctx: env.OLLAMA_NUM_CTX
    }
  }
}
