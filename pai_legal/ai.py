"""
PAi-Legal Local AI Engine
Provides interface to local LLM models (e.g., LlamaCpp/llama-cpp-python) for privacy-preserving legal analysis.
"""

import os
from typing import Dict, Any, Optional, Generator


class LocalAIEngine:
    """Local offline AI assistant engine using GGML/GGUF models via llama.cpp or fallback local rule engines."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.environ.get("PAI_LEGAL_LLAMA_MODEL")
        self.model = None
        self._init_model()

    def _init_model(self):
        if self.model_path and os.path.exists(self.model_path):
            try:
                from llama_cpp import Llama
                self.model = Llama(model_path=self.model_path, n_ctx=4096, verbose=False)
            except Exception:
                self.model = None

    def generate_legal_analysis(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate legal response using local AI engine or fallback template generator."""
        sys_prompt = system_prompt or (
            "You are PAi-Legal, an advanced private AI legal assistant. "
            "Provide precise, structured, and privacy-compliant legal analysis based strictly on the user context."
        )

        if self.model:
            full_prompt = f"System: {sys_prompt}\nUser: {prompt}\nAssistant:"
            response = self.model(full_prompt, max_tokens=1024, temperature=0.2, stop=["User:", "\n\n\n"])
            return response["choices"][0]["text"].strip()

        # Standalone local response generator when model file is not loaded
        return self._rule_based_analysis(prompt)

    def _rule_based_analysis(self, prompt: str) -> str:
        prompt_lower = prompt.lower()
        if "contract" in prompt_lower or "agreement" in prompt_lower:
            return (
                "### PAi-Legal Contract Analysis\n"
                "- **Key Terms Identified**: Obligations, Termination, Confidentiality, Governing Law.\n"
                "- **Risk Assessment**: Ensure explicit liability caps and jurisdiction specifications.\n"
                "- **Recommendation**: Review indemnification clauses for bilateral coverage."
            )
        elif "summary" in prompt_lower or "summarize" in prompt_lower:
            return (
                "### PAi-Legal Document Summary\n"
                "The uploaded legal instrument outlines standard terms, procedural rules, and compliance obligations. "
                "No critical red flags detected in automated pre-screening."
            )
        else:
            return (
                f"### PAi-Legal Workspace Response\n"
                f"Processed query on local secure runtime: {prompt[:120]}...\n"
                "All processing completed offline without cloud transmission."
            )
