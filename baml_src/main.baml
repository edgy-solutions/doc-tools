

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
