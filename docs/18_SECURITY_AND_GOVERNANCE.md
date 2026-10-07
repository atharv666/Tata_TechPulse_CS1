
---

# `18_LLM_PROVIDER_ABSTRACTION.md`

```md
# LLM Provider Abstraction

## 1. Purpose

The application must not hard-code a specific LLM provider.

The architecture must support:

```text
approved enterprise/private model
NVIDIA-compatible endpoint
OpenAI-compatible endpoint
local Ollama model
future private deployment