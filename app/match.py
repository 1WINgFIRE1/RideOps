"""Find past tickets that describe the same problem.

Score (0-100) = half *meaning* + half *shared words*:
  * meaning: a small embedding model (BAAI/bge-small-en-v1.5 via fastembed; free, runs on the laptop
    CPU, ~70 MB downloaded once) turns each text into 384 numbers. Texts that mean the same thing get
    similar numbers, so "transport never arrived" finds "Cab did not turn up".
  * shared words: catches exact details the model blurs, e.g. "booking cutoff" vs "cancelled bookings".
On 36 client-style rewordings (app/match_eval.py) the top match is right 94% of the time, vs 89% with
words alone; 6 of 7 brand-new problems correctly get "no close match". If the model can't be loaded (offline on first run), words alone are used.
"""
import os
from functools import cache

import numpy as np
from rapidfuzz import fuzz, utils

MODEL = "BAAI/bge-small-en-v1.5"
MIN_SCORE = 65   # below this the ticket is treated as a new kind of issue (calibrated in app/match_eval.py)
CACHE_DIR = os.environ.get("RIDEOPS_MODEL_DIR", os.path.join(os.path.dirname(__file__), "..", "data", ".models"))


@cache
def _model():
    try:
        from fastembed import TextEmbedding
        local = os.environ.get("RIDEOPS_EMBED_PATH")  # a folder with the model files, for offline machines
        return TextEmbedding(MODEL, specific_model_path=local) if local else TextEmbedding(MODEL, cache_dir=CACHE_DIR)
    except Exception as e:  # noqa: BLE001 - any failure means "use the fallback"
        print(f"[match] embedding model unavailable, using word matching instead: {e}")
        return None


def method() -> str:
    return "meaning (embeddings)" if _model() is not None else "words (fallback)"


_vectors: dict[str, np.ndarray] = {}


def _embed(texts: list[str]) -> np.ndarray:
    """Vectors for texts, computed once per distinct text and then reused."""
    todo = [t for t in dict.fromkeys(texts) if t not in _vectors]
    if todo:
        for t, v in zip(todo, _model().embed(todo)):
            _vectors[t] = v / np.linalg.norm(v)
    return np.array([_vectors[t] for t in texts])


def scores(text: str, choices: list[str]) -> list[tuple[str, float]]:
    """Every choice with its similarity to the text (0-100), best first."""
    if not text or not choices:
        return []
    words = np.array([fuzz.token_set_ratio(text, c, processor=utils.default_process) for c in choices], dtype=float)
    if _model() is None:
        total = words
    else:
        meaning = np.clip(_embed(choices) @ _embed([text])[0], 0, 1) * 100
        total = 0.5 * meaning + 0.5 * words
    order = np.argsort(-total, kind="stable")
    return [(choices[i], float(total[i])) for i in order]


def best_match(text: str, choices: list[str]) -> tuple[str | None, float]:
    hits = scores(text, choices)
    if not hits:
        return None, 0.0
    best, score = hits[0]
    return (best, score) if score >= MIN_SCORE else (None, score)


def similar(text: str, choices: list[str], min_score: float) -> list[tuple[str, float]]:
    """Every choice that matches the text at least `min_score` well (other wordings of the same problem)."""
    return [(c, s) for c, s in scores(text, choices) if s >= min_score]
