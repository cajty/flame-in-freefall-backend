"""Optional ONNX cross-encoder reranker for PSI catalog search.

The model is exported offline to ONNX and loaded through onnxruntime, so the
API stays portable across CPU vendors. OCI's `CI.Standard.E5.Flex` is AMD,
where OpenVINO is unsupported; onnxruntime runs on the same x86-64 image.

A reranker only reorders records returned by BM25. It never creates records,
text or citations. When the model is disabled, missing or fails, the search
tool keeps the BM25 order.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger("flame_atlas.reranker")

# Title, acronym and research area come first in the rerank text, so 256
# tokens keep the signal while cutting CPU latency well inside the 5 s tool
# timeout. Raise it only after measuring the deployment CPU.
MAX_SEQUENCE_LENGTH = 256
BATCH_SIZE = 16
MODEL_FILE = "model.onnx"
TOKENIZER_FILE = "tokenizer.json"


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """Return one relevance score per document; higher means more relevant."""


class OnnxCrossEncoderReranker:
    """Cross-encoder scoring through onnxruntime. CPU only by design."""

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = model_dir / MODEL_FILE
        tokenizer_path = model_dir / TOKENIZER_FILE
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise FileNotFoundError(
                f"reranker model needs {MODEL_FILE} and {TOKENIZER_FILE} in {model_dir}"
            )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=MAX_SEQUENCE_LENGTH)
        self._tokenizer.enable_padding()
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_names = {item.name for item in self._session.get_inputs()}
        self._output_name = self._session.get_outputs()[0].name

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        scores: list[float] = []
        for start in range(0, len(documents), BATCH_SIZE):
            batch = documents[start : start + BATCH_SIZE]
            encodings = self._tokenizer.encode_batch(
                [(query, document) for document in batch]
            )
            feeds = {
                "input_ids": np.array([item.ids for item in encodings], dtype=np.int64),
                "attention_mask": np.array(
                    [item.attention_mask for item in encodings], dtype=np.int64
                ),
            }
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = np.array(
                    [item.type_ids for item in encodings], dtype=np.int64
                )
            logits = self._session.run([self._output_name], feeds)[0]
            scores.extend(_positive_scores(logits))
        return scores


def _positive_scores(logits: np.ndarray) -> list[float]:
    values = np.asarray(logits)
    if values.ndim != 2:
        raise ValueError(f"reranker output must be 2-D, got shape {values.shape}")
    if values.shape[1] == 1:
        return (1.0 / (1.0 + np.exp(-values[:, 0]))).tolist()
    if values.shape[1] == 2:
        shifted = values - values.max(axis=1, keepdims=True)
        probabilities = np.exp(shifted)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities[:, 1].tolist()
    raise ValueError(
        f"reranker output must have 1 or 2 columns, got shape {values.shape}"
    )


@lru_cache(maxsize=4)
def load_reranker(model_dir: Path) -> Reranker | None:
    """Load the reranker once per process.

    Returns None when the runtime or model is unavailable. Callers fall back to
    BM25 order; a request must never fail because the optional model is missing.
    """
    if not model_dir.is_dir():
        logger.warning("Reranker model directory is missing: %s", model_dir)
        return None
    try:
        reranker = OnnxCrossEncoderReranker(model_dir)
    except ImportError as error:
        logger.warning("Reranker dependencies are not installed: %s", error)
        return None
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning(
            "Reranker model could not be loaded from %s: %s", model_dir, error
        )
        return None
    logger.info("Reranker loaded from %s", model_dir)
    return reranker
