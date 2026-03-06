"""
Ollama integration utilities for ProtoScore V2.

Handles:
- Ollama connectivity checks
- Installed model discovery
- Smart model recommendation based on system RAM and quality tiers
- Auto-pull with streaming progress
- Chat completions with JSON mode
"""

import json
import os
import platform
import logging
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_URL = "http://localhost:11434"

# ---------------------------------------------------------------------------
# Model Tier System — ranked by extraction quality for clinical protocols
# ---------------------------------------------------------------------------

# Tier 1: Best quality, needs 48GB+ RAM
# Tier 2: Great quality/speed balance, needs 16GB+ RAM
# Tier 3: Good quality, runs on 8GB+ RAM

MODEL_TIERS: dict[str, dict] = {
    # Tier 1 — Best
    "llama3.1:70b":       {"tier": 1, "params": "70B", "min_ram_gb": 48},
    "qwen2.5:72b":        {"tier": 1, "params": "72B", "min_ram_gb": 48},
    "deepseek-v3:latest": {"tier": 1, "params": "67B", "min_ram_gb": 48},
    "command-r-plus:latest": {"tier": 1, "params": "104B", "min_ram_gb": 64},
    # Tier 2 — Great
    "llama3.1:8b":        {"tier": 2, "params": "8B", "min_ram_gb": 8},
    "qwen2.5:14b":        {"tier": 2, "params": "14B", "min_ram_gb": 16},
    "gemma2:27b":         {"tier": 2, "params": "27B", "min_ram_gb": 20},
    "mistral-nemo:12b":   {"tier": 2, "params": "12B", "min_ram_gb": 12},
    "deepseek-r1:14b":    {"tier": 2, "params": "14B", "min_ram_gb": 16},
    # Tier 3 — Good
    "llama3.2:3b":        {"tier": 3, "params": "3B", "min_ram_gb": 4},
    "qwen2.5:7b":         {"tier": 3, "params": "7B", "min_ram_gb": 8},
    "gemma2:9b":          {"tier": 3, "params": "9B", "min_ram_gb": 8},
    "mistral:7b":         {"tier": 3, "params": "7B", "min_ram_gb": 8},
    "phi3:14b":           {"tier": 3, "params": "14B", "min_ram_gb": 12},
}

TIER_LABELS = {1: "Best", 2: "Great", 3: "Good"}

# Default pull targets per RAM tier (what to auto-pull if nothing installed)
DEFAULT_PULL_MODEL = {
    "high":   "llama3.1:70b",   # 48GB+ RAM
    "medium": "llama3.1:8b",    # 16GB+ RAM
    "low":    "llama3.2:3b",    # < 16GB RAM
}


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

def get_system_ram_gb() -> float:
    """Return total system RAM in GB."""
    try:
        if platform.system() == "Darwin":
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return int(out.strip()) / (1024 ** 3)
        else:
            # Linux
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
    except Exception:
        pass
    return 16.0  # safe default


# ---------------------------------------------------------------------------
# Ollama connectivity
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.getenv("OLLAMA_HOST", OLLAMA_DEFAULT_URL).rstrip("/")


def check_ollama_running() -> bool:
    """Return True if Ollama is reachable."""
    try:
        r = requests.get(f"{_base_url()}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False
    except Exception:
        return False


def get_installed_models() -> list[str]:
    """Return list of installed model names (e.g. ['llama3.1:8b', 'mistral:7b'])."""
    try:
        r = requests.get(f"{_base_url()}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Smart model recommendation
# ---------------------------------------------------------------------------

def _normalize_model_name(name: str) -> str:
    """Normalize model name for matching (strip :latest, etc.)."""
    if ":" not in name:
        return name + ":latest"
    return name


def recommend_model(
    installed_models: list[str],
    ram_gb: float | None = None,
) -> tuple[str, int, str]:
    """
    Pick the best model from installed_models based on quality tier.
    If nothing suitable is installed, recommend what to pull.

    Returns:
        (model_name, tier_number, human_rationale)
    """
    if ram_gb is None:
        ram_gb = get_system_ram_gb()

    # Score installed models against tier list
    best_match: tuple[int, str, dict] | None = None
    for model in installed_models:
        normalized = _normalize_model_name(model)
        # Check exact match or prefix match
        for tier_model, info in MODEL_TIERS.items():
            if normalized == tier_model or model.startswith(tier_model.split(":")[0]):
                if info["min_ram_gb"] <= ram_gb:
                    if best_match is None or info["tier"] < best_match[0]:
                        best_match = (info["tier"], model, info)
                break

    if best_match:
        tier, model, info = best_match
        label = TIER_LABELS[tier]
        rationale = (
            f"Using {model} (Tier {tier} — {label}, "
            f"{info['params']} parameters). "
            f"Well-suited for clinical protocol extraction."
        )
        return model, tier, rationale

    # Nothing suitable installed — recommend a pull
    if ram_gb >= 48:
        pull = DEFAULT_PULL_MODEL["high"]
    elif ram_gb >= 16:
        pull = DEFAULT_PULL_MODEL["medium"]
    else:
        pull = DEFAULT_PULL_MODEL["low"]

    info = MODEL_TIERS[pull]
    rationale = (
        f"No suitable model installed. Recommended: {pull} "
        f"(Tier {info['tier']} — {TIER_LABELS[info['tier']]}, "
        f"{info['params']} params, fits your {ram_gb:.0f}GB RAM)."
    )
    return pull, info["tier"], rationale


# ---------------------------------------------------------------------------
# Model pulling
# ---------------------------------------------------------------------------

def pull_model(
    model_name: str,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> bool:
    """
    Pull a model from Ollama registry with streaming progress.

    Args:
        model_name: e.g. "llama3.1:8b"
        progress_callback: Called with (status_message, fraction 0.0-1.0)

    Returns:
        True if pull succeeded.
    """
    url = f"{_base_url()}/api/pull"
    try:
        with requests.post(
            url,
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=600,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                status = data.get("status", "")

                # Calculate progress from download bytes
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                fraction = completed / total if total > 0 else 0.0

                if progress_callback:
                    progress_callback(f"Pulling {model_name}: {status}", fraction)

                if status == "success":
                    return True

        return True
    except Exception as e:
        logger.error(f"Failed to pull model {model_name}: {e}")
        return False


# ---------------------------------------------------------------------------
# Chat completions (JSON mode)
# ---------------------------------------------------------------------------

def call_ollama_chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = True,
    timeout: int = 300,
) -> dict:
    """
    Call Ollama chat API and return parsed JSON response.

    Args:
        model: Ollama model name
        system_prompt: System message
        user_prompt: User message (should include JSON schema instructions)
        json_mode: If True, set format="json" to enforce JSON output
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON dict from model response
    """
    url = f"{_base_url()}/api/chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,  # Low temp for structured extraction
            "num_ctx": 32768,    # Large context for protocol documents
        },
    }

    if json_mode:
        payload["format"] = "json"

    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()

    content = response.json()["message"]["content"]

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Model returned invalid JSON: {content[:200]}...")


# ---------------------------------------------------------------------------
# Status helpers for the UI
# ---------------------------------------------------------------------------

def get_ollama_status_html() -> str:
    """Build an HTML status widget for the Ollama connection and model."""
    if not check_ollama_running():
        return (
            '<div style="padding:10px; background:#2a1515; border:1px solid #F44336; '
            'border-radius:8px; margin:8px 0; font-size:0.85em;">'
            '<span style="color:#F44336; font-weight:700;">&#x2717; Ollama Not Running</span><br>'
            '<span style="color:#ccc;">Install from '
            '<a href="https://ollama.com" target="_blank" style="color:#00A3E0;">ollama.com</a>, '
            'then run <code style="background:#333; padding:2px 6px; border-radius:3px;">ollama serve</code></span>'
            '</div>'
        )

    installed = get_installed_models()
    model, tier, rationale = recommend_model(installed)
    tier_color = {1: "#4CAF50", 2: "#00A3E0", 3: "#FF9800"}.get(tier, "#888")

    if model in [m for m in installed]:
        status_icon = '<span style="color:#4CAF50; font-weight:700;">&#x2713; Connected</span>'
        model_line = (
            f'<span style="color:{tier_color}; font-weight:600;">'
            f'Model: {model}</span> '
            f'<span style="background:{tier_color}; color:#000; padding:2px 8px; '
            f'border-radius:10px; font-size:0.8em; font-weight:600;">'
            f'Tier {tier} — {TIER_LABELS[tier]}</span>'
        )
    else:
        status_icon = '<span style="color:#FF9800; font-weight:700;">&#x26A0; No Model</span>'
        model_line = (
            f'<span style="color:#ccc;">{rationale}</span><br>'
            f'<span style="color:#aaa; font-size:0.85em;">Will auto-pull when you click Analyze.</span>'
        )

    return (
        f'<div style="padding:10px; background:#1a1a2e; border:1px solid #333; '
        f'border-radius:8px; margin:8px 0; font-size:0.85em;">'
        f'{status_icon}<br>'
        f'{model_line}'
        f'</div>'
    )
