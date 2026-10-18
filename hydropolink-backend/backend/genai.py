"""
Grounded generative summary (Predictive AI -> Generative AI).

The predictive models decide; the LLM only turns their structured output
into plain language. Guardrail: every number in the LLM's text must appear
in the facts we gave it, otherwise we discard it and use the template. The
LLM never sees anything beyond the station's public telemetry.

Set HYDROLINK_LLM_URL to any OpenAI-compatible endpoint running on the
LinuxONE VM (llama.cpp server, Ollama, vLLM), e.g.
  HYDROLINK_LLM_URL=http://hydrolink-llm:8080/v1/chat/completions
Unset = template only (still works, demo never breaks).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple

import requests

LLM_URL = os.getenv("HYDROLINK_LLM_URL")
LLM_MODEL = os.getenv("HYDROLINK_LLM_MODEL", "local")
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def template_summary(f: Dict[str, Any]) -> str:
    if f["status"] == "healthy":
        extra = (f" GloFAS models {f['glofas_flow_m3s']} m3/s here, consistent with the gauge."
                 if f.get("glofas_flow_m3s") is not None else "")
        return (f"Station {f['station_id']} ({f['name']}) is operating normally at "
                f"{f.get('signal_value', f['current_value'])}{f.get('unit', 'm')}, within its expected range of {f['expected_range']}; the next "
                f"reading is forecast at {f['forecast']}{f.get('unit', 'm')}. Trust score {f['trust_score']}%.{extra}")
    why = "; ".join(f.get("reasons") or ["anomaly model flagged this reading"])
    return (f"Station {f['station_id']} ({f['name']}) needs manual review: {why}. Observed "
            f"{f.get('signal_value', f['current_value'])}{f.get('unit', 'm')} against an expected {f['expected_range']}; trust score "
            f"{f['trust_score']}%. Automated public alerts are held until a person verifies it.")


def _numbers_grounded(text: str, facts: Dict[str, Any]) -> bool:
    allowed = set(NUM.findall(" ".join(str(v) for v in facts.values())))
    allowed |= {"0", "1", "2", "100"}
    return all(n in allowed for n in NUM.findall(text))


def summarize(facts: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (summary, engine) where engine is 'llm' or 'template'."""
    if not LLM_URL:
        return template_summary(facts), "template"
    prompt = ("You write 2-3 sentence status notes for South African water officials. "
              "Use ONLY the facts given. Do not invent numbers, causes, or advice. "
              "If status is review_required, say a human must verify before any public alert.\n"
              f"FACTS: {facts}")
    try:
        r = requests.post(LLM_URL, timeout=20, json={
            "model": LLM_MODEL, "temperature": 0.2, "max_tokens": 160,
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        if text and _numbers_grounded(text, facts):
            return text, "llm"
        print("[genai] LLM output failed grounding check; using template")
    except Exception as e:
        print(f"[genai] LLM unavailable: {e}")
    return template_summary(facts), "template"
