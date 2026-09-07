# Using Hyusk with OpenRouter

OpenRouter provides access to multiple LLM providers through a single API. You can use any model available on OpenRouter with Hyusk.

## Setup

### 1. Get an OpenRouter API Key

1. Go to https://openrouter.ai/
2. Sign up and get your API key
3. Copy your API key

### 2. Configure Hyusk for OpenRouter

Edit your `.env` file:

```bash
# Use OpenAI provider with OpenRouter base URL
OPENAI_API_KEY=your_openrouter_api_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1

# Set OpenAI as the default provider
DEFAULT_LLM_PROVIDER=openai

# Specify the model you want to use
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
```

### 3. Available Models

OpenRouter supports many models. Some popular options:

**Anthropic Models:**
```bash
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
DEFAULT_MODEL=anthropic/claude-3-opus
DEFAULT_MODEL=anthropic/claude-3-haiku
```

**OpenAI Models:**
```bash
DEFAULT_MODEL=openai/gpt-4-turbo
DEFAULT_MODEL=openai/gpt-4
DEFAULT_MODEL=openai/gpt-3.5-turbo
```

**Google Models:**
```bash
DEFAULT_MODEL=google/gemini-pro
DEFAULT_MODEL=google/palm-2
```

**Meta Models:**
```bash
DEFAULT_MODEL=meta-llama/llama-3-70b
DEFAULT_MODEL=meta-llama/llama-3-8b
```

**Other Models:**
```bash
DEFAULT_MODEL=mistralai/mistral-7b
DEFAULT_MODEL=cohere/command-r
DEFAULT_MODEL=perplexity/pplx-70b-online
```

See the full list at: https://openrouter.ai/models

## Configuration Examples

### Example 1: Claude via OpenRouter

```bash
# .env
OPENAI_API_KEY=sk-or-v1-xxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
DEFAULT_LLM_PROVIDER=openai
DEFAULT_MODEL=anthropic/claude-3.5-sonnet

# Model routing
FAST_MODEL=anthropic/claude-3-haiku
CODING_MODEL=anthropic/claude-3.5-sonnet
VISION_MODEL=anthropic/claude-3.5-sonnet
```

### Example 2: Multiple Models

```bash
# .env
OPENAI_API_KEY=sk-or-v1-xxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
DEFAULT_LLM_PROVIDER=openai

# Use different models for different purposes
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
FAST_MODEL=openai/gpt-3.5-turbo
CODING_MODEL=anthropic/claude-3.5-sonnet
VISION_MODEL=openai/gpt-4-vision
```

### Example 3: Local Model Server

If you're running a local OpenAI-compatible server (like LM Studio, Ollama with OpenAI compatibility, etc.):

```bash
# .env
OPENAI_API_KEY=not-needed
OPENAI_BASE_URL=http://localhost:1234/v1
DEFAULT_LLM_PROVIDER=openai
DEFAULT_MODEL=local-model
```

## YAML Configuration

You can also configure this in `~/.config/hyusk/config.yaml`:

```yaml
llm:
  default_provider: openai
  openai_api_key: sk-or-v1-xxx
  openai_base_url: https://openrouter.ai/api/v1
  
  default_model: anthropic/claude-3.5-sonnet
  fast_model: anthropic/claude-3-haiku
  coding_model: anthropic/claude-3.5-sonnet
  vision_model: anthropic/claude-3.5-sonnet
  
  max_tokens: 4096
  temperature: 0.7
```

## Usage

Once configured, use Hyusk normally:

```bash
# Start chat
hyusk chat

# The model will be selected based on your configuration
You: Hello!
Hyusk: [Using your configured OpenRouter model]
```

## OpenRouter-Specific Features

### Site Name and App URL

OpenRouter allows you to set site information for better tracking:

Edit `src/hyusk/llm/providers/openai.py` and add custom headers:

```python
self.client = AsyncOpenAI(
    api_key=self.api_key,
    base_url=base_url,
    timeout=float(timeout),
    default_headers={
        "HTTP-Referer": "https://your-site.com",
        "X-Title": "Your App Name",
    }
)
```

### Model Fallbacks

OpenRouter supports automatic fallbacks. Your request will use the best available model if your primary choice is unavailable.

### Cost Tracking

OpenRouter provides cost tracking in their dashboard. Each request shows:
- Model used
- Tokens consumed
- Cost per request

## Troubleshooting

### Error: "Invalid API Key"

Make sure your OpenRouter API key starts with `sk-or-v1-` and is correctly copied.

### Error: "Model not found"

Check that the model name is correct. Use the exact format from OpenRouter's model list (e.g., `anthropic/claude-3.5-sonnet`, not just `claude-3.5-sonnet`).

### Tool Calling Issues

Not all models on OpenRouter support tool calling. For best results with Hyusk's tool system, use:
- Anthropic Claude models (full support)
- OpenAI GPT-4/GPT-3.5 (full support)
- Google Gemini (experimental support)

### Streaming Issues

If streaming doesn't work, check that:
1. The model supports streaming
2. Your base URL is correct
3. You're using a recent version of the OpenAI client library

## Pricing

OpenRouter pricing varies by model:
- GPT-3.5 Turbo: ~$0.50-2/M tokens
- Claude 3 Haiku: ~$0.25-1.25/M tokens
- Claude 3.5 Sonnet: ~$3-15/M tokens
- GPT-4 Turbo: ~$10-30/M tokens

Check current prices at: https://openrouter.ai/models

## Advanced: Mixing Providers

You can use OpenRouter alongside direct API access:

```bash
# .env
# Direct Anthropic access for primary model
ANTHROPIC_API_KEY=sk-ant-xxx
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4

# OpenRouter for alternative models
OPENAI_API_KEY=sk-or-v1-xxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
FAST_MODEL=meta-llama/llama-3-8b
```

Then in code or config, you can specify which provider to use for different tasks.

## Benefits of OpenRouter

1. **Access to Multiple Models**: Try different models without multiple API keys
2. **Cost Optimization**: Route to cheaper models for simple tasks
3. **Automatic Fallbacks**: If a model is down, OpenRouter tries alternatives
4. **Unified Billing**: One bill for all LLM usage
5. **Model Comparison**: Easy to test and compare models

## Security Note

Your OpenRouter API key has access to your account. Keep it secure:
- Never commit `.env` to version control
- Use environment variables in production
- Rotate keys regularly
- Monitor usage in OpenRouter dashboard

---

For more information, visit:
- OpenRouter Documentation: https://openrouter.ai/docs
- OpenRouter Models: https://openrouter.ai/models
- OpenRouter API Keys: https://openrouter.ai/keys
