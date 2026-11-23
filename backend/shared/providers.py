"""Provider adapter: business logic depends on generate(), not on a vendor SDK."""
import os
from typing import Protocol

import boto3

from shared.common import anthropic_api_key


class LLMProvider(Protocol):
    def generate(self, messages, *, system=None, max_tokens=800, tools=None) -> dict: ...


class ClaudeProvider:
    """Anthropic Messages API. timeout/max_retries keep a call inside the Lambda limit."""

    def __init__(self, model=None, client=None, timeout=22.0, max_retries=0):
        from anthropic import Anthropic
        self.model = model or os.environ["CLAUDE_MODEL"]
        self.client = client or Anthropic(api_key=anthropic_api_key(),
                                          timeout=timeout, max_retries=max_retries)

    def generate(self, messages, *, system=None, max_tokens=800, tools=None):
        kwargs = dict(model=self.model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        r = self.client.messages.create(**kwargs)
        return {"text": "".join(b.text for b in r.content if b.type == "text"),
                "content": r.content, "stop_reason": r.stop_reason,
                "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                "provider": "anthropic", "model": self.model}


class BedrockProvider:
    """Amazon Bedrock Converse API (IAM auth, no API key). Text only."""

    def __init__(self, model=None, client=None):
        self.model = model or os.environ["BEDROCK_MODEL_ID"]
        self.client = client or boto3.client("bedrock-runtime")

    def generate(self, messages, *, system=None, max_tokens=800, tools=None):
        if tools:
            raise NotImplementedError("Tool use is not wired for the Bedrock adapter.")
        kwargs = dict(modelId=self.model,
                      messages=[{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
                      inferenceConfig={"maxTokens": max_tokens})
        if system:
            kwargs["system"] = [{"text": system}]
        r = self.client.converse(**kwargs)
        text = "".join(p.get("text", "") for p in r["output"]["message"]["content"])
        u = r.get("usage", {})
        return {"text": text, "stop_reason": r.get("stopReason"),
                "input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0),
                "provider": "bedrock", "model": self.model}


def get_provider(spec=None, **kw):
    """spec: 'anthropic:<model>' or 'bedrock:<model-id>'; default from env PROVIDER/CLAUDE_MODEL."""
    kind, _, model = (spec or os.environ.get("PROVIDER", "anthropic")).partition(":")
    if kind == "bedrock":
        return BedrockProvider(model or None, **kw)
    return ClaudeProvider(model or None, **kw)
