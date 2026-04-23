"""Provider-agnostic LLM wrapper that routes chat through a selectable backend."""

import os
import re
import logging
from typing import Optional

from app.llm_backends import (
    BackendError,
    BackendToolsUnsupported,
    ModelBackend,
    OllamaBackend,
)
from app.mode_loader import ModeLoader

logger = logging.getLogger("professor_tux")

DEFAULT_MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
DEFAULT_TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))


PERSONA_BASE = """\
You are Professor Tux, a cybersecurity teacher.
Identity rule: you are Professor Tux. If asked what model, AI, LLM, provider, company, or system powers you, or asked for a version, vendor, or technical stack, answer only as Professor Tux and decline to name any underlying model. Do not confirm or deny specific model or provider names. Never mention Ollama, OpenAI, Anthropic, Google, Meta, Mistral, Gemma, Qwen, Llama, GPT, Claude, or any other model or vendor name.
Be concise by default.
For greetings or small talk, reply briefly and do not start teaching.
For cybersecurity questions, teach clearly and safely.
Never provide exploit code or offensive instructions that enable harm.
When the search_lectures tool is available, CALL IT FIRST for any question that could touch course material — the student's uploaded lectures are the course of record and take precedence over your training knowledge. Only skip the tool for pure greetings or small talk.
When the tool returns lecture material, summarize it naturally and cite slide numbers when relevant."""

RECALL_MODE_HARD_RULES = """\
Recall Mode hard rules:
- Never reveal the final answer, full definition, or worked solution.
- Give only one small hint and one short follow-up question.
- If the student asks for the answer directly, refuse briefly and suggest Guided Learning.
- Keep the response short and hint-focused."""

RECALL_MODE_MCQ_RULES = """\
This student message is a multiple-choice or option-based exam question.
- Do not identify the correct option letter.
- Do not quote or restate the correct option text.
- Do not say "the answer is", "pick", "choose", or "it is option X".
- Give only one tiny concept-level hint that helps the student decide."""

WRONG_TURN_HARD_RULES = """\
This turn is an intentional close-but-wrong turn.
- Intentionally give a plausible but incorrect answer related to the student's topic.
- Stay close to the real topic so the answer sounds believable.
- Never reveal that the answer is intentionally wrong, experimental, or misleading.
- Vary the type of mistake when possible: swap adjacent concepts, invert a relationship, misstate a default value, or over-attribute a property."""

WRONG_TURN_RECALL_RULES = """\
For recall-style wrong turns:
- Keep the reply very short, like a recall cue.
- The cue itself should be misleading but still adjacent to the real concept.
- Do not reveal the real answer."""

WRONG_TURN_GUIDED_RULES = """\
For guided-style wrong turns:
- Explain smoothly and confidently in a teaching tone.
- Ensure at least one central claim is wrong while staying on-topic.
- Do not hedge by saying you might be wrong."""

LECTURE_CONTEXT_HEADER = """\
LECTURE MATERIAL (use this to answer — reference slides when relevant):
"""


def _strip_thinking(text: str, *, trim: bool = True) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', text or "", flags=re.DOTALL)
    return cleaned.strip() if trim else cleaned


class ProfessorTux:
    """Routes chat generation through a selectable model provider."""

    _GREETING_PHRASES = {
        "hello", "hi", "hey", "hello there", "hi there", "hey there",
        "good morning", "good afternoon", "good evening", "yo", "sup",
        "whats up", "what is up",
    }
    _THANKS_PHRASES = {
        "thanks", "thank you", "thanks a lot", "thank you very much", "thx",
    }
    _FAREWELL_PHRASES = {
        "bye", "goodbye", "see you", "see you later", "later", "catch you later",
    }

    def __init__(self, mode_loader: ModeLoader):
        self._mode_loader = mode_loader
        self._max_tokens = DEFAULT_MAX_TOKENS
        self._temperature = DEFAULT_TEMPERATURE
        ollama_backend = OllamaBackend(
            provider_label="Ollama",
            default_description="Ollama endpoint",
        )
        self._backends: dict[str, ModelBackend] = {
            "ollama": ollama_backend,
        }

        self._active_provider: str = ""
        self._active_model: str = ""
        self._tool_support: dict[str, bool] = {}
        self._select_default_target()

    @property
    def is_loaded(self) -> bool:
        if not self._active_provider or not self._active_model:
            return False
        backend = self._backends.get(self._active_provider)
        return backend.is_ready(self._active_model) if backend else False

    @property
    def model_name(self) -> str:
        if not self._active_provider or not self._active_model:
            return ""
        return f"{self._active_provider}:{self._active_model}"

    @property
    def active_provider(self) -> str:
        return self._active_provider

    @property
    def active_model(self) -> str:
        return self._active_model

    def _select_default_target(self):
        preferred_provider = "ollama" if "ollama" in self._backends else ""
        if not preferred_provider and self._backends:
            preferred_provider = next(iter(self._backends))
        if not preferred_provider:
            return

        backend = self._backends[preferred_provider]
        if backend.default_model:
            self._active_provider = preferred_provider
            self._active_model = backend.default_model

    def list_available_models(self) -> list[dict]:
        models: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for backend in self._backends.values():
            for descriptor in backend.list_models():
                key = (descriptor.provider, descriptor.model)
                if key in seen:
                    continue
                seen.add(key)
                models.append({
                    "selection": descriptor.selection,
                    "provider": descriptor.provider,
                    "provider_label": getattr(backend, "provider_label", descriptor.provider),
                    "model": descriptor.model,
                    "label": descriptor.label,
                    "description": descriptor.description,
                    "active": key == (self._active_provider, self._active_model),
                })

        active_key = (self._active_provider, self._active_model)
        if self._active_provider and self._active_model and active_key not in seen:
            backend = self._backends.get(self._active_provider)
            models.insert(0, {
                "selection": f"{self._active_provider}::{self._active_model}",
                "provider": self._active_provider,
                "provider_label": getattr(backend, "provider_label", self._active_provider.title()),
                "model": self._active_model,
                "label": self._active_model,
                "description": "Configured default",
                "active": True,
            })

        return sorted(
            models,
            key=lambda item: (
                0 if item["active"] else 1,
                item["provider_label"].lower(),
                item["label"].lower(),
            ),
        )

    def switch_model(self, provider: str, model: str):
        backend = self._backends.get(provider)
        if not backend:
            raise ValueError(f"Unsupported provider: {provider}")
        backend.validate_model(model)
        self._active_provider = provider
        self._active_model = model
        logger.info("Active model target set to %s:%s", provider, model)

    def _get_active_backend(self) -> ModelBackend:
        if not self._active_provider or not self._active_model:
            raise RuntimeError("No model target configured")
        backend = self._backends.get(self._active_provider)
        if not backend:
            raise RuntimeError(f"Backend is not available: {self._active_provider}")
        return backend

    def get_backend(self, provider: str) -> Optional[ModelBackend]:
        return self._backends.get(provider)

    def tool_support_cached(self, model: str) -> Optional[bool]:
        return self._tool_support.get(model)

    def probe_tool_support(self, model: str) -> Optional[bool]:
        """
        Return True/False if the model supports tool calling, or None on unrelated
        backend errors. Results are cached so repeated calls are cheap.
        """
        if not model:
            return None
        cached = self._tool_support.get(model)
        if cached is not None:
            return cached

        backend = self._backends.get(self._active_provider) if self._active_provider else None
        if backend is None:
            backend = next(iter(self._backends.values()), None)
        if backend is None:
            return None

        probe_tools = [{
            "type": "function",
            "function": {
                "name": "probe",
                "description": "capability probe",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        try:
            backend.chat(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                tools=probe_tools,
                max_tokens=1,
                temperature=0.0,
            )
            self._tool_support[model] = True
            return True
        except BackendToolsUnsupported:
            self._tool_support[model] = False
            return False
        except BackendError as exc:
            logger.warning("Tool-support probe failed for %s: %s", model, exc)
            return None

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def configure_generation(
        self,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        if max_tokens is not None:
            self._max_tokens = max(1, int(max_tokens))
        if temperature is not None:
            self._temperature = float(temperature)

    def configure_backend(self, *, base_url: Optional[str] = None):
        current = self._backends.get("ollama")
        default_model = current.default_model if current else None
        backend = OllamaBackend(
            provider_label="Ollama",
            default_description="Ollama endpoint",
            base_url=base_url,
            default_model=default_model,
        )
        self._backends["ollama"] = backend
        if self._active_provider == "ollama" and self._active_model:
            return
        if not self._active_provider and backend.default_model:
            self._active_provider = "ollama"
            self._active_model = backend.default_model

    @staticmethod
    def _normalize_social_text(text: str) -> str:
        cleaned = text.lower()
        cleaned = re.sub(r"\b(professor tux|professor|tux|prof)\b", "", cleaned)
        cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def social_message_kind(self, text: str) -> Optional[str]:
        normalized = self._normalize_social_text(text)
        if normalized in self._GREETING_PHRASES:
            return "greeting"
        if normalized in self._THANKS_PHRASES:
            return "thanks"
        if normalized in self._FAREWELL_PHRASES:
            return "farewell"
        return None

    def is_social_message(self, text: str) -> bool:
        return self.social_message_kind(text) is not None

    def social_response(self, text: str, mode_id: str) -> Optional[str]:
        kind = self.social_message_kind(text)
        if kind == "greeting":
            if self._is_recall_mode(mode_id):
                return "Hey! Ready when you are. Give me a cybersecurity topic and I'll help you work it out."
            return "Hey! Ready when you are. Give me a cybersecurity topic and I'll break it down clearly."
        if kind == "thanks":
            return "You're welcome. Send the next cybersecurity question whenever you're ready."
        if kind == "farewell":
            return "See you next time."
        return None

    @staticmethod
    def _is_recall_mode(mode_id: str) -> bool:
        normalized = (mode_id or "").strip().lower()
        return normalized == "recall" or normalized.startswith("recall_")

    @staticmethod
    def _is_wrong_mode(mode_id: str) -> bool:
        normalized = (mode_id or "").strip().lower()
        return normalized.endswith("_wrong")

    @staticmethod
    def _is_multiple_choice_prompt(text: str) -> bool:
        if not text:
            return False
        normalized = text.lower()
        if "mcq" in normalized or "multiple choice" in normalized:
            return True
        option_patterns = [
            r"(?:^|\n)\s*[a-d][\).\:-]\s+.+",
            r"(?:^|\n)\s*[1-4][\).\:-]\s+.+",
            r"\boption\s+[a-d]\b",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in option_patterns)

    def _max_tokens_for_mode(self, mode_id: str) -> int:
        if self._is_recall_mode(mode_id):
            return min(self._max_tokens, 96)
        return self._max_tokens

    def _temperature_for_mode(self, mode_id: str, apply_wrongness: bool = False) -> float:
        if self._is_wrong_mode(mode_id) and apply_wrongness:
            return max(self._temperature, 1.05)
        return self._temperature

    def build_messages(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
        apply_wrongness: bool = False,
        lecture_tool_hint: str = "",
    ) -> list[dict]:
        mode_def = self._mode_loader.get_mode(mode_id)
        mode_rules = mode_def.system_prompt if mode_def else ""
        mode_name = mode_def.name if mode_def else "Default"

        rules, examples = self._split_mode_prompt(mode_rules)

        parts = [PERSONA_BASE]
        parts.append(f"\n\nYou are in {mode_name}. {rules}")
        if self._is_recall_mode(mode_id):
            parts.append(f"\n\n{RECALL_MODE_HARD_RULES}")
            if self._is_multiple_choice_prompt(student_message):
                parts.append(f"\n\n{RECALL_MODE_MCQ_RULES}")
        if self._is_wrong_mode(mode_id) and apply_wrongness:
            parts.append(f"\n\n{WRONG_TURN_HARD_RULES}")
            if self._is_recall_mode(mode_id):
                parts.append(f"\n\n{WRONG_TURN_RECALL_RULES}")
            else:
                parts.append(f"\n\n{WRONG_TURN_GUIDED_RULES}")

        if topic:
            parts.append(f"\nCurrent topic: {topic}.")

        if lecture_tool_hint:
            parts.append(f"\n\n{lecture_tool_hint}")

        if lecture_context:
            parts.append(f"\n\n{LECTURE_CONTEXT_HEADER}{lecture_context}")

        system_prompt = "".join(parts)
        messages = [{"role": "system", "content": system_prompt}]

        # Few-shot examples — small models learn expected behavior by imitation.
        for ex in examples:
            messages.append({"role": "user", "content": ex["student"]})
            messages.append({"role": "assistant", "content": ex["response"]})

        for msg in history[-16:]:
            role = "user" if msg["role"] == "student" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": student_message})
        return messages

    def chat_once(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        mode_id: str = "",
        apply_wrongness: bool = False,
    ) -> dict:
        backend = self._get_active_backend()
        model = self._active_model
        effective_tools = None if self._tool_support.get(model) is False else tools
        temperature = self._temperature_for_mode(mode_id, apply_wrongness)
        try:
            response = backend.chat(
                model=model,
                messages=messages,
                tools=effective_tools,
                max_tokens=self._max_tokens,
                temperature=temperature,
            )
            if effective_tools:
                self._tool_support[model] = True
        except BackendToolsUnsupported as e:
            if effective_tools is None:
                logger.error("LLM chat failed: %s", e)
                raise
            logger.info("Model %s does not support tools; retrying without tools", model)
            self._tool_support[model] = False
            try:
                response = backend.chat(
                    model=model,
                    messages=messages,
                    tools=None,
                    max_tokens=self._max_tokens,
                    temperature=temperature,
                )
            except BackendError as inner:
                logger.error("LLM chat failed: %s", inner)
                raise
        except BackendError as e:
            logger.error("LLM chat failed: %s", e)
            raise

        message = response.get("message") or {}
        content = _strip_thinking(message.get("content", ""))
        normalized = {
            "role": message.get("role", "assistant"),
            "content": content,
        }
        if message.get("tool_calls"):
            normalized["tool_calls"] = message["tool_calls"]
        if message.get("thinking"):
            normalized["thinking"] = message["thinking"]
        return normalized

    def chat_stream_once(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        mode_id: str = "",
        apply_wrongness: bool = False,
    ):
        backend = self._get_active_backend()
        model = self._active_model
        temperature = self._temperature_for_mode(mode_id, apply_wrongness)
        effective_tools = None if self._tool_support.get(model) is False else tools

        attempts: list[list[dict] | None] = [effective_tools]
        if effective_tools is not None:
            attempts.append(None)

        yielded = False
        for attempt_tools in attempts:
            try:
                for chunk in backend.chat_stream(
                    model=model,
                    messages=messages,
                    tools=attempt_tools,
                    max_tokens=self._max_tokens,
                    temperature=temperature,
                ):
                    yielded = True
                    message = chunk.get("message") or {}
                    content = _strip_thinking(message.get("content", ""), trim=False)
                    normalized = {
                        "role": message.get("role", "assistant"),
                        "content": content,
                        "done": bool(chunk.get("done")),
                        "done_reason": chunk.get("done_reason"),
                    }
                    if message.get("tool_calls"):
                        normalized["tool_calls"] = message["tool_calls"]
                    if message.get("thinking"):
                        normalized["thinking"] = message["thinking"]
                    yield normalized
                if attempt_tools:
                    self._tool_support[model] = True
                return
            except BackendToolsUnsupported as e:
                if yielded or attempt_tools is None:
                    logger.error("LLM streaming chat failed: %s", e)
                    raise
                logger.info("Model %s does not support tools; retrying without tools", model)
                self._tool_support[model] = False
                continue
            except BackendError as e:
                logger.error("LLM streaming chat failed: %s", e)
                raise

    @staticmethod
    def _split_mode_prompt(prompt: str) -> tuple[str, list[dict]]:
        """Split a mode prompt body into rule text and **Student:**/**Response:** few-shot pairs."""
        examples = []
        rule_lines = []
        lines = prompt.split("\n")

        i = 0
        in_examples = False
        while i < len(lines):
            line = lines[i].strip()

            if line.lower().startswith("## example") or line.lower().startswith("## response"):
                in_examples = True
                i += 1
                continue

            if in_examples and line.startswith("**Student:**"):
                student_text = line.replace("**Student:**", "").strip().strip('"')
                response_lines = []
                i += 1
                while i < len(lines):
                    rline = lines[i].strip()
                    if rline.startswith("---") or rline.startswith("**Student:**"):
                        break
                    if rline and not rline.startswith("**Response:**"):
                        response_lines.append(rline)
                    i += 1
                if student_text and response_lines:
                    examples.append({
                        "student": student_text,
                        "response": "\n".join(response_lines),
                    })
                continue

            if not in_examples and line and not line.startswith("#") and not line.startswith("---"):
                rule_lines.append(line)

            i += 1

        rules = " ".join(rule_lines)
        # Small models do better with short rules; cap at ~500 chars.
        if len(rules) > 500:
            rules = rules[:497] + "..."

        return rules, examples

    def generate(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
        apply_wrongness: bool = False,
    ) -> str:
        social_response = self.social_response(student_message, mode_id)
        if social_response is not None:
            return social_response

        backend = self._get_active_backend()

        messages = self.build_messages(
            student_message, mode_id, topic, history, lecture_context, apply_wrongness
        )

        try:
            content = backend.generate(
                model=self._active_model,
                messages=messages,
                max_tokens=self._max_tokens_for_mode(mode_id),
                temperature=self._temperature_for_mode(mode_id, apply_wrongness),
            )
        except BackendError as e:
            logger.error("LLM request failed: %s", e)
            return "⚠️ The teaching engine is unavailable right now. Please try again shortly."

        content = _strip_thinking(content)
        if content:
            return content
        return "⚠️ I couldn't finish that answer. Please ask again."

    def generate_stream(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
        apply_wrongness: bool = False,
    ):
        social_response = self.social_response(student_message, mode_id)
        if social_response is not None:
            yield social_response
            return

        backend = self._get_active_backend()

        messages = self.build_messages(
            student_message, mode_id, topic, history, lecture_context, apply_wrongness
        )

        try:
            stream = backend.generate_stream(
                model=self._active_model,
                messages=messages,
                max_tokens=self._max_tokens_for_mode(mode_id),
                temperature=self._temperature_for_mode(mode_id, apply_wrongness),
            )

            buffer = ""
            in_think = False
            for token in stream:
                if not token:
                    continue

                buffer += token

                # Suppress <think>...</think> blocks from streaming output.
                if not in_think:
                    if "<think>" in buffer:
                        before = buffer[:buffer.index("<think>")]
                        if before:
                            yield before
                        buffer = buffer[buffer.index("<think>"):]
                        in_think = True
                    else:
                        # Hold back 6 chars so a partial "<think>" split across chunks isn't emitted.
                        if len(buffer) > 6:
                            safe = buffer[:-6]
                            buffer = buffer[-6:]
                        else:
                            safe = ""
                        if safe:
                            yield safe
                else:
                    if "</think>" in buffer:
                        after = buffer[buffer.index("</think>") + 8:]
                        buffer = after
                        in_think = False

            if not in_think and buffer:
                yield buffer

        except BackendError as e:
            logger.error("LLM stream failed: %s", e)
            yield "\n\n⚠️ The teaching engine is unavailable right now. Please try again shortly."
