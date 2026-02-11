"""
NVIDIA Kimi Integration (NvidiaBrain)
Allows ATLAS to send long text for deep reasoning and receive structured outputs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import requests


class NvidiaBrain:
    """
    Nvidia Kimi brain for deep reasoning on long text.
    """

    INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
    MODEL = "moonshotai/kimi-k2.5"

    def __init__(self, api_key: Optional[str] = None, stream: bool = False):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY", "")
        self.stream = stream

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream" if self.stream else "application/json"
        }

    def _build_prompt(self, text: str) -> List[Dict[str, str]]:
        system = (
            "You are a risk and sentiment analyst. Return ONLY valid JSON with keys:\n"
            "sentiment_score: float between -1.0 and 1.0\n"
            "risk_flags: list of short strings\n"
            "Do not include any other text."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": text}
        ]

    def _normalize_flag(self, flag: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(flag).lower()).strip("_")
        return normalized or "unknown_risk"

    def _normalize_analysis(self, result: Dict) -> Dict:
        sentiment_raw = result.get("sentiment_score", 0.0)
        try:
            sentiment_score = float(sentiment_raw)
        except (TypeError, ValueError):
            sentiment_score = 0.0
        sentiment_score = max(-1.0, min(1.0, sentiment_score))

        flags_raw = result.get("risk_flags", [])
        if isinstance(flags_raw, str):
            flags_raw = [flags_raw]
        if not isinstance(flags_raw, list):
            flags_raw = []
        risk_flags = [self._normalize_flag(flag) for flag in flags_raw]

        return {
            "sentiment_score": sentiment_score,
            "risk_flags": risk_flags
        }

    def _parse_json(self, raw: str) -> Dict:
        try:
            return self._normalize_analysis(json.loads(raw))
        except Exception:
            # Try to extract JSON blob
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    return self._normalize_analysis(json.loads(match.group(0)))
                except Exception:
                    pass
        return self._normalize_analysis({"sentiment_score": 0.0, "risk_flags": ["nvidia_parse_failed"]})

    def _parse_sse_stream(self, response: requests.Response) -> Dict:
        content_parts: List[str] = []
        fallback_parts: List[str] = []

        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break

            fallback_parts.append(payload)
            try:
                chunk = json.loads(payload)
            except Exception:
                continue

            # NVIDIA/OpenAI-style chunk format.
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if isinstance(delta, dict):
                    piece = delta.get("content")
                    if isinstance(piece, str):
                        content_parts.append(piece)
                elif isinstance(choice.get("message"), dict):
                    piece = choice["message"].get("content")
                    if isinstance(piece, str):
                        content_parts.append(piece)

        if content_parts:
            return self._parse_json("".join(content_parts))
        return self._parse_json("\n".join(fallback_parts))

    def analyze_sentiment_and_risks(self, text: str) -> Dict:
        """
        Analyze sentiment and risks from text.
        Returns: {"sentiment_score": float, "risk_flags": [str, ...]}
        """
        if not self.api_key:
            return self._normalize_analysis({"sentiment_score": 0.0, "risk_flags": ["nvidia_call_failed"]})

        payload = {
            "model": self.MODEL,
            "messages": self._build_prompt(text),
            "max_tokens": 16384,
            "temperature": 1.00,
            "top_p": 1.00,
            "stream": self.stream,
            "chat_template_kwargs": {"thinking": True}
        }

        try:
            response = requests.post(self.INVOKE_URL, headers=self._headers(), json=payload, timeout=60)
            if response.status_code != 200:
                return self._normalize_analysis({"sentiment_score": 0.0, "risk_flags": ["nvidia_call_failed"]})

            if self.stream:
                return self._parse_sse_stream(response)

            data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return self._parse_json(content)
        except Exception:
            return self._normalize_analysis({"sentiment_score": 0.0, "risk_flags": ["nvidia_call_failed"]})
