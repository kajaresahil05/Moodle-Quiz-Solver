"""
app/services/gemini_service.py
Google Gemini API integration for quiz answer suggestions.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from app.config import get_settings
from app.models import GeminiAnswer, QuizOption, QuestionType

import time

logger = logging.getLogger(__name__)

# Cache timestamp until which Gemini is known to be daily rate-limited
_gemini_daily_exhausted_until: float = 0.0


class GeminiService:
    """Handles all interactions with the Google Gemini API."""

    def __init__(self) -> None:
        self._client = None
        self._model: Optional[str] = None

    def _get_client(self):
        """Lazy-initialize Gemini client."""
        if self._client is None:
            settings = get_settings()
            if not settings.gemini_configured:
                raise RuntimeError(
                    "GEMINI_API_KEY is not configured. Please set it in your .env file."
                )
            try:
                from google import genai
                self._client = genai.Client(api_key=settings.gemini_api_key)
                self._model = settings.gemini_model
                logger.info("Gemini client initialized with model: %s", self._model)
            except ImportError:
                raise RuntimeError(
                    "google-genai package not installed. Run: pip install google-genai"
                )
        return self._client

    async def get_answer_suggestion(
        self,
        question_text: str,
        options: List[QuizOption],
        question_type: QuestionType,
        context: str = "",
    ) -> GeminiAnswer:
        """
        Suggest the best answer(s) for a quiz question with cascading fallback:
        1. Gemini (primary, auto-switches to Groq if daily quota reached)
        2. Groq (fallback 1 / 14,400 daily requests)
        3. Ollama (fallback 2)
        """
        global _gemini_daily_exhausted_until
        if not question_text.strip():
            return GeminiAnswer(is_ambiguous=True, explanation="Empty question text")

        prompt = self._build_prompt(question_text, options, question_type, context)
        settings = get_settings()
        primary_choice = getattr(settings, "primary_ai_provider", "auto").lower()

        # If user explicitly set primary=groq OR Gemini daily quota is currently exhausted, try Groq first
        groq_first = (primary_choice == "groq") or (time.time() < _gemini_daily_exhausted_until)

        if groq_first and settings.groq_configured:
            try:
                ans = await self._call_groq(prompt, options)
                if ans and ans.selected_option_ids:
                    return ans
            except Exception as e:
                logger.warning("Groq call failed (%s). Attempting Gemini...", e)

        # Try Gemini
        if time.time() >= _gemini_daily_exhausted_until and settings.gemini_configured:
            try:
                return await self._call_gemini(prompt, options)
            except Exception as e:
                logger.warning("Gemini call failed (%s). Attempting Groq fallback...", e)

        # Fallback to Groq if not already tried
        if not groq_first and settings.groq_configured:
            try:
                ans = await self._call_groq(prompt, options)
                if ans and ans.selected_option_ids:
                    return ans
                logger.warning("Groq returned empty selections. Attempting Ollama fallback...")
            except Exception as e:
                logger.warning("Groq fallback call failed (%s). Attempting Ollama fallback...", e)

        # Fallback to Ollama
        try:
            ans = await self._call_ollama(prompt, options)
            if ans and ans.selected_option_ids:
                return ans
        except Exception as e:
            logger.warning("Ollama fallback call failed (%s). All providers exhausted.", e)

        return GeminiAnswer(
            is_ambiguous=True,
            explanation="All AI providers (Gemini, Groq, Ollama) failed to answer question",
            confidence=0.0,
        )

    async def _call_gemini(self, prompt: str, options: List[QuizOption]) -> GeminiAnswer:
        """Call Google Gemini API with rate-limit retry."""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                client = self._get_client()
                import asyncio
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self._model,
                        contents=prompt,
                        config={
                            "response_mime_type": "application/json",
                            "temperature": 0.1,
                        }
                    )
                )

                raw_text = response.text.strip()
                provider_name = f"Gemini ({self._model or 'gemini-2.5-flash'})"
                logger.info("Answer obtained from %s", provider_name)
                return self._parse_response(raw_text, options, ai_provider=provider_name)

            except Exception as e:
                err_str = str(e)
                is_daily_exhausted = any(phrase in err_str.lower() for phrase in ["per day", "daily", "free_tier_requests"]) or ("h" in err_str and "retry in" in err_str)
                if is_daily_exhausted:
                    global _gemini_daily_exhausted_until
                    _gemini_daily_exhausted_until = time.time() + 1800
                    logger.warning("Gemini daily quota exhausted for today. Auto-routing workflows to Groq (14,400 RPD).")
                elif ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                    wait_time = 12.0
                    match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                    if match:
                        wait_time = float(match.group(1)) + 1.0
                    logger.warning(
                        "Gemini rate limit hit (429). Retrying in %.1fs...", wait_time
                    )
                    import asyncio
                    await asyncio.sleep(wait_time)
                    continue
                raise

    async def _call_groq(self, prompt: str, options: List[QuizOption]) -> GeminiAnswer:
        """Call Groq API as first fallback."""
        settings = get_settings()
        if not settings.groq_configured:
            raise RuntimeError("Groq API key not configured")

        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
            raw_text = data["choices"][0]["message"]["content"]
            provider_name = f"Groq ({settings.groq_model})"
            logger.info("Answer obtained from %s", provider_name)
            return self._parse_response(raw_text, options, ai_provider=provider_name)

    async def _call_ollama(self, prompt: str, options: List[QuizOption]) -> GeminiAnswer:
        """Call Ollama local server as second fallback."""
        settings = get_settings()
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
        }
        url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            raw_text = data.get("message", {}).get("content", "")
            provider_name = f"Ollama ({settings.ollama_model})"
            logger.info("Answer obtained from %s", provider_name)
            return self._parse_response(raw_text, options, ai_provider=provider_name)

    def _build_prompt(
        self,
        question_text: str,
        options: List[QuizOption],
        question_type: QuestionType,
        context: str = "",
    ) -> str:
        """Build a structured prompt for Gemini."""
        options_text = "\n".join(
            f"  {opt.option_id}. {opt.text}" for opt in options
        )
        multi_note = (
            "This is a MULTIPLE SELECT question — you may select more than one option."
            if question_type == QuestionType.MULTI
            else "This is a SINGLE SELECT question — select exactly one option."
        )

        prompt = f"""You are an academic assistant helping a student understand quiz material.
Answer the following quiz question accurately.

{multi_note}

QUESTION:
{question_text}

OPTIONS:
{options_text}

{f"CONTEXT: {context}" if context else ""}

Respond ONLY with a valid JSON object matching this schema:
{{
  "selected_option_ids": ["<option_id>", ...],
  "explanation": "<brief explanation of why these options are correct>",
  "confidence": <float between 0.0 and 1.0>,
  "is_ambiguous": <true if you cannot determine the answer reliably>,
  "requires_image": <true if the question requires an image you cannot see>
}}

Important rules:
- selected_option_ids must only contain IDs from the options list: {[o.option_id for o in options]}
- For single-select, include exactly one ID unless ambiguous
- confidence should reflect how certain you are
- If the question requires visual content, set requires_image to true
- Never fabricate option IDs not in the list above
"""
        return prompt

    def _parse_response(self, raw: str, options: List[QuizOption], ai_provider: str = "Gemini") -> GeminiAnswer:
        """Parse Gemini JSON response into GeminiAnswer."""
        valid_ids = {o.option_id for o in options}

        try:
            # Try to extract JSON from markdown code blocks if present
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if json_match:
                raw = json_match.group(1)

            data = json.loads(raw)

            # Validate selected_option_ids against actual options
            selected = [
                sid for sid in data.get("selected_option_ids", [])
                if sid in valid_ids
            ]

            return GeminiAnswer(
                selected_option_ids=selected,
                explanation=str(data.get("explanation", ""))[:1000],
                confidence=float(data.get("confidence", 0.5)),
                is_ambiguous=bool(data.get("is_ambiguous", False)),
                requires_image=bool(data.get("requires_image", False)),
                ai_provider=ai_provider,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse AI response: %s | Raw: %s", e, raw[:200])
            return GeminiAnswer(
                is_ambiguous=True,
                explanation="Could not parse AI response",
                confidence=0.0,
                ai_provider=ai_provider,
            )

    async def test_connection(self) -> bool:
        """Test that the Gemini API is reachable and key is valid."""
        ok, _ = await self.test_connection_detailed()
        return ok

    async def test_connection_detailed(self) -> tuple[bool, str]:
        """Test Gemini API connectivity with descriptive status message."""
        import asyncio
        settings = get_settings()
        if not settings.gemini_configured:
            return False, "GEMINI_API_KEY is not configured in .env"

        model_name = settings.gemini_model or "gemini-3.5-flash"
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents="Reply with OK",
            )
            return True, f"Connected ({model_name})"
        except Exception as e:
            err_msg = str(e)
            logger.error("Gemini connection test failed: %s", err_msg)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                return False, f"Daily limit reached for {model_name}"
            if "404" in err_msg or "NOT_FOUND" in err_msg:
                return False, f"Model {model_name} unavailable"
            return False, f"Error: {err_msg[:80]}"

    async def test_groq(self) -> tuple[bool, str]:
        """Test Groq API connectivity."""
        settings = get_settings()
        if not settings.groq_configured:
            return False, "Groq API key is not configured in .env"
        import httpx
        try:
            headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
                if res.status_code == 200:
                    return True, f"Connected to Groq ({settings.groq_model})"
                return False, f"Groq returned HTTP {res.status_code}"
        except Exception as e:
            return False, f"Groq connection failed: {e}"

    async def test_ollama(self) -> tuple[bool, str]:
        """Test local Ollama server connectivity."""
        settings = get_settings()
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    found = any(settings.ollama_model in m for m in models)
                    if found:
                        return True, f"Ollama online. Model '{settings.ollama_model}' is ready."
                    return True, f"Ollama online, but model '{settings.ollama_model}' is not pulled yet (run: ollama pull {settings.ollama_model})"
                return False, f"Ollama returned HTTP {res.status_code}"
        except Exception as e:
            return False, f"Ollama offline ({settings.ollama_base_url})"
