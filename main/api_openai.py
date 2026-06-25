# Optional OpenAI summary at the top of results.
# No key? We write a basic comparison instead.

from __future__ import annotations

from typing import Any

from settings import OPENAI_API_KEY


class LLMService:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or OPENAI_API_KEY
        self._client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def generate_recommendation_summary(
        self,
        top_destinations: list[dict[str, Any]],
        user_preferences: dict[str, Any],
    ) -> str:
        if not self._client:
            return self._fallback_summary(top_destinations, user_preferences)

        prompt = self._build_prompt(top_destinations, user_preferences)
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You help someone pick a tropical holiday with decent nightlife. "
                            "Keep it brief, plain text, no markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.7,
            )
            content = response.choices[0].message.content or ""
            return content.replace("**", "") or self._fallback_summary(top_destinations, user_preferences)
        except Exception:
            return self._fallback_summary(top_destinations, user_preferences)

    @staticmethod
    def _build_prompt(dests: list[dict[str, Any]], prefs: dict[str, Any]) -> str:
        lines = [
            f"User wants: max budget ${prefs.get('max_budget', 3000)}, "
            f"prefers temp {prefs.get('min_temp', 26)}-{prefs.get('max_temp', 34)} C, "
            f"nightlife priority: {prefs.get('nightlife_weight', 0.3):.0%}.",
            "Top ranked destinations:",
        ]
        for i, d in enumerate(dests[:3], 1):
            lines.append(
                f"{i}. {d['name']} — score {d['score']}, "
                f"{d['temp_max_c']} C, ${d['total_cost_usd']} est., "
                f"{d['nightlife_total']} nightlife venues nearby."
            )
        lines.append("Write a short paragraph (about 150 words) comparing these places. Plain text only.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(dests: list[dict[str, Any]], prefs: dict[str, Any]) -> str:
        if not dests:
            return "Nothing matched — try a bigger budget or wider temp range."
        top = dests[0]
        alt = dests[1] if len(dests) > 1 else None
        text = (
            f"Best bet: {top['name']} ({top['score']}/100) — "
            f"{top['temp_max_c']}°C highs, about ${top['total_cost_usd']:,.0f} for 7 nights, "
            f"{top['nightlife_total']} bars/clubs nearby."
        )
        if alt:
            text += (
                f" {alt['name']} is second at ${alt['total_cost_usd']:,.0f} "
                f"if you want to compare price and weather."
            )
        return text
