import json
import re

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


def mock_mode() -> bool:
    return not settings.llm_api_key


def chat(messages: list[dict], max_tokens: int | None = None, json_mode: bool = False) -> str:
    if mock_mode():
        return _mock_reply(messages, json_mode)
    body = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": max_tokens or settings.max_output_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        resp = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"LLM provider error {exc.response.status_code}: {exc.response.text[:300]}")
    except Exception as exc:
        raise LLMError(f"LLM call failed: {exc}")


def parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LLMError("Model did not return JSON")
        return json.loads(match.group(0))


def _mock_reply(messages: list[dict], json_mode: bool) -> str:
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if json_mode:
        questions = []
        topics = ["core definitions", "key processes", "practical applications"]
        for i in range(3):
            questions.append(
                {
                    "question": f"Mock Q{i + 1}: which statement best describes the material's {topics[i]}?",
                    "options": [
                        "Option A",
                        "Option B",
                        "Option C",
                        f"Option D (correct for Q{i + 1})",
                    ],
                    "answer_index": 3,
                    "explanation": "Mock explanation referencing the source material.",
                }
            )
        return json.dumps({"questions": questions})
    words = len(last_user.split())
    return (
        "### Summary (mock mode)\n\n"
        f"Processed ~{words} words of prompt context.\n\n"
        "- The system is running without an LLM_API_KEY\n"
        "- All agent features return deterministic mock content\n"
        "- Set LLM_API_KEY to unlock real generation\n"
    )
