"""Small HTTP clients for chat-completion style LLM providers.

The implementation intentionally avoids provider SDKs so local installs stay
lightweight. Providers are configured through YAML and environment variables.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class LLMConfigError(ValueError):
    """Raised when LLM configuration is missing or invalid."""


class LLMProviderError(RuntimeError):
    """Raised when a provider call fails or returns an invalid response."""


PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "api_key_required": True,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_required": True,
    },
    "openai_compatible": {
        "api_key_env": "OPENAI_API_KEY",
        "api_key_required": False,
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
    },
}


def _without_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def resolve_provider_config(
    llm_config: Dict[str, Any],
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge global, provider-specific, and request-level LLM config."""
    overrides = _without_none(overrides or {})
    provider = overrides.get("provider") or llm_config.get("provider")
    if not provider:
        raise LLMConfigError("llm.provider 未配置")

    provider = str(provider)
    if provider not in PROVIDER_DEFAULTS and provider != "openai_compatible":
        raise LLMConfigError(f"不支持的 LLM provider: {provider}")

    merged: Dict[str, Any] = {}
    merged.update(PROVIDER_DEFAULTS.get(provider, {}))
    merged.update({key: value for key, value in llm_config.items() if key != "providers"})
    merged.update((llm_config.get("providers") or {}).get(provider, {}))
    merged.update(overrides)
    merged["provider"] = provider

    model = merged.get("model") or merged.get("model_name")
    if not model:
        raise LLMConfigError("llm.model_name 未配置")
    merged["model"] = model

    merged["temperature"] = float(merged.get("temperature", 0.2))
    merged["max_tokens"] = int(merged.get("max_tokens", 800))
    merged["timeout_seconds"] = int(merged.get("timeout_seconds", 60))
    return merged


def _post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout_seconds: int,
) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMProviderError(f"LLM provider HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LLMProviderError(f"LLM provider 连接失败: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMProviderError("LLM provider 返回的不是合法 JSON") from exc


def _api_key(config: Dict[str, Any]) -> str:
    key = config.get("api_key")
    if key:
        return str(key)
    key_env = config.get("api_key_env")
    if key_env and os.environ.get(str(key_env)):
        return str(os.environ[str(key_env)])
    if not config.get("api_key_required", True):
        return ""
    raise LLMConfigError(f"缺少 LLM API Key，请设置环境变量 {key_env or 'API_KEY'}")


def _call_openai_compatible(config: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    base_url = str(config.get("base_url") or "").rstrip("/")
    if not base_url:
        raise LLMConfigError("OpenAI-compatible provider 需要配置 base_url")

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
    }
    headers = {"Content-Type": "application/json"}
    api_key = _api_key(config)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = _post_json(
        url=f"{base_url}/chat/completions",
        payload=payload,
        headers=headers,
        timeout_seconds=config["timeout_seconds"],
    )
    choices = data.get("choices") or []
    if not choices:
        raise LLMProviderError("LLM provider 没有返回 choices")
    message = choices[0].get("message") or {}
    answer = message.get("content")
    if not answer:
        raise LLMProviderError("LLM provider 没有返回回答内容")
    return {
        "answer": answer,
        "provider": config["provider"],
        "model": config["model"],
        "usage": data.get("usage") or {},
        "raw": data,
    }


def _call_ollama(config: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    base_url = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": config["model"],
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config["temperature"],
            "num_predict": config["max_tokens"],
        },
    }
    data = _post_json(
        url=f"{base_url}/api/chat",
        payload=payload,
        headers={"Content-Type": "application/json"},
        timeout_seconds=config["timeout_seconds"],
    )
    message = data.get("message") or {}
    answer = message.get("content") or data.get("response")
    if not answer:
        raise LLMProviderError("Ollama 没有返回回答内容")
    return {
        "answer": answer,
        "provider": config["provider"],
        "model": config["model"],
        "usage": {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
        },
        "raw": data,
    }


def call_chat_model(
    llm_config: Dict[str, Any],
    messages: List[Dict[str, str]],
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call the configured chat model and return normalized output."""
    config = resolve_provider_config(llm_config, overrides)
    provider = config["provider"]
    if provider in {"openai", "deepseek", "openai_compatible"}:
        return _call_openai_compatible(config, messages)
    if provider == "ollama":
        return _call_ollama(config, messages)
    raise LLMConfigError(f"不支持的 LLM provider: {provider}")
