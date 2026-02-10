"""
Professor Tux — LLM wrapper around DASD-4B-Thinking-GGUF.
==========================================================
Uses the ModeLoader to dynamically build system prompts from
mode definition files. No hardcoded mode logic.
"""

import os
import logging
from typing import Optional

from llama_cpp import Llama
from app.mode_loader import ModeLoader

logger = logging.getLogger("professor_tux")

# ── Configuration ────────────────────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "./models/DASD-4B-Thinking.Q4_K_M.gguf")
N_CTX = int(os.getenv("N_CTX", "4096"))
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "0"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))


# ── Base persona (shared across ALL modes) ───────────────────────────
PERSONA_BASE = """\
You are **Professor Tux** 🐧, a seasoned cybersecurity instructor with 20+ years \
of experience in penetration testing, digital forensics, network security, \
cryptography, and incident response. You are patient, encouraging, and \
passionate about helping students truly *understand* cybersecurity — not just \
memorize facts.

Rules you ALWAYS follow:
- Stay strictly within cybersecurity, networking, and related CS topics.
- If a student asks something off-topic, gently redirect them.
- Use real-world analogies and examples (CTFs, CVEs, MITRE ATT&CK, OWASP).
- Adjust complexity to the student's apparent level.
- Never provide actual exploit code that could be used maliciously; \
  teach concepts and defensive thinking instead.
"""

LECTURE_CONTEXT_INSTRUCTIONS = """
━━━ LECTURE CONTEXT INSTRUCTIONS ━━━
You have been provided with excerpts from the student's actual lecture slides below. \
When answering:
1. **Prioritize lecture material** — ground your explanations in what the student's \
   instructor has actually taught. Reference specific slides when helpful.
2. **Bridge gaps** — if the lecture material partially covers the topic, supplement \
   with your own knowledge but clearly distinguish what's from lectures vs your additions.
3. **Correct misalignments** — if the student's question contradicts the lecture \
   material, gently point this out.
4. **Don't fabricate slide references** — only cite slides that appear in the \
   provided context.
"""


class ProfessorTux:
    """Wraps the GGUF model. Uses ModeLoader for dynamic prompt construction."""

    def __init__(self, mode_loader: ModeLoader):
        self._llm: Optional[Llama] = None
        self._mode_loader = mode_loader
        self._model_path: str = MODEL_PATH

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    @property
    def model_name(self) -> str:
        return os.path.basename(self._model_path)

    def load_model(self):
        """Load the GGUF model from a local file path."""
        self._load_from_path(self._model_path)

    def load_model_by_path(self, path: str):
        """Swap to a different GGUF model at runtime."""
        if self._llm is not None:
            del self._llm
            self._llm = None
        self._model_path = path
        self._load_from_path(path)

    def _load_from_path(self, path: str):
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Model not found at '{path}'. "
                f"Set MODEL_PATH env var to your .gguf file."
            )

        logger.info("⏳ Loading model from %s (n_ctx=%d, n_gpu_layers=%d) …",
                     path, N_CTX, N_GPU_LAYERS)
        self._llm = Llama(
            model_path=path,
            n_ctx=N_CTX,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )
        logger.info("✅ Professor Tux is ready!")

    def _build_messages(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
    ) -> list[dict]:
        """Build the chat-completion messages list dynamically from mode files."""

        # Get mode-specific prompt from loader
        mode_prompt = self._mode_loader.get_prompt(mode_id)
        if not mode_prompt:
            mode_prompt = "Answer the student's cybersecurity question helpfully."

        # Assemble full system prompt
        parts = [PERSONA_BASE, "\n", mode_prompt]

        if lecture_context:
            parts.extend(["\n\n", LECTURE_CONTEXT_INSTRUCTIONS, "\n\n", lecture_context])

        if topic:
            parts.append(
                f"\n\nThe current session topic is: **{topic}**. "
                f"Keep your responses focused on this topic."
            )

        system_prompt = "".join(parts)
        messages = [{"role": "system", "content": system_prompt}]

        # Conversation history (last 20 turns to fit context)
        for msg in history[-20:]:
            role = "user" if msg["role"] == "student" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": student_message})
        return messages

    def generate(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
    ) -> str:
        """Generate Professor Tux's response using the specified mode."""
        if not self._llm:
            raise RuntimeError("Model not loaded")

        messages = self._build_messages(
            student_message, mode_id, topic, history, lecture_context
        )

        result = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["Student:", "student:", "\n\nUser:"],
        )

        content = result["choices"][0]["message"]["content"].strip()

        # Strip thinking content from reasoning models (e.g., <think>...</think>)
        import re
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

        return content

    def generate_stream(
        self,
        student_message: str,
        mode_id: str,
        topic: Optional[str],
        history: list[dict],
        lecture_context: str = "",
    ):
        """Yield tokens as they are generated (for SSE streaming)."""
        if not self._llm:
            raise RuntimeError("Model not loaded")

        messages = self._build_messages(
            student_message, mode_id, topic, history, lecture_context
        )

        import re
        stream = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["Student:", "student:", "\n\nUser:"],
            stream=True,
        )

        buffer = ""
        in_think = False
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            token = delta.get("content", "")
            if not token:
                continue

            buffer += token

            # Suppress <think>...</think> blocks from streaming output
            if not in_think:
                if "<think>" in buffer:
                    # Yield everything before <think>
                    before = buffer[:buffer.index("<think>")]
                    if before:
                        yield before
                    buffer = buffer[buffer.index("<think>"):]
                    in_think = True
                else:
                    # Only yield if we're sure we're not mid-tag
                    safe = buffer
                    # Hold back a few chars in case "<think>" is being built up
                    if len(buffer) > 6:
                        safe = buffer[:-6]
                        buffer = buffer[-6:]
                    else:
                        safe = ""
                    if safe:
                        yield safe
            else:
                # Inside <think> block, don't yield
                if "</think>" in buffer:
                    after = buffer[buffer.index("</think>") + 8:]
                    buffer = after
                    in_think = False

        # Flush remaining buffer
        if not in_think and buffer:
            yield buffer
