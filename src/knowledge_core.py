from __future__ import annotations

from dataclasses import dataclass
from math import log
from pathlib import Path
import re
from typing import Iterable

DEFAULT_KNOWLEDGE_PATH = Path("data/knowledge")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
HEADING_PATTERN = re.compile(r"^(#{2,3})\s+(.*)$")


@dataclass(slots=True)
class KnowledgeChunk:
    chunk_id: str
    source_path: str
    heading: str
    level: int
    body: str
    priority_score: float = 1.0


@dataclass(slots=True)
class SearchHit:
    chunk: KnowledgeChunk
    score: float
    terms: list[str]


class KnowledgeCore:
    def __init__(self, knowledge_path: str | Path = DEFAULT_KNOWLEDGE_PATH) -> None:
        self.knowledge_path = Path(knowledge_path)
        self.knowledge_path.mkdir(parents=True, exist_ok=True)
        self._chunks: list[KnowledgeChunk] = []
        self._doc_freq: dict[str, int] = {}
        self._term_freqs: list[dict[str, int]] = []
        self._doc_lengths: list[int] = []
        self._avg_doc_length: float = 0.0
        self.rebuild_index()

    def rebuild_index(self) -> None:
        self._chunks = self._load_chunks()
        self._term_freqs = []
        self._doc_freq = {}
        self._doc_lengths = []

        for chunk in self._chunks:
            tokens = self.tokenize(f"{chunk.heading}\n{chunk.body}")
            term_freqs: dict[str, int] = {}
            seen_terms: set[str] = set()
            for token in tokens:
                term_freqs[token] = term_freqs.get(token, 0) + 1
                if token not in seen_terms:
                    self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
                    seen_terms.add(token)
            self._term_freqs.append(term_freqs)
            self._doc_lengths.append(len(tokens))

        total_terms = sum(self._doc_lengths)
        self._avg_doc_length = total_terms / len(self._doc_lengths) if self._doc_lengths else 0.0

    def _load_chunks(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for path in sorted(self.knowledge_path.rglob("*.md")):
            chunks.extend(self._chunk_markdown(path))
        return chunks

    def _chunk_markdown(self, path: Path) -> list[KnowledgeChunk]:
        lines = path.read_text(encoding="utf-8").splitlines()
        chunks: list[KnowledgeChunk] = []
        current_heading = path.stem
        current_level = 1
        current_lines: list[str] = []
        chunk_index = 0
        priority_score = 1.0

        def flush() -> None:
            nonlocal chunk_index, current_lines, priority_score
            body = "\n".join(current_lines).strip()
            if not body:
                current_lines = []
                priority_score = 1.0
                return
            chunk_id = f"{path.as_posix()}#{chunk_index}"
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    source_path=path.as_posix(),
                    heading=current_heading,
                    level=current_level,
                    body=body,
                    priority_score=priority_score,
                )
            )
            chunk_index += 1
            current_lines = []
            priority_score = 1.0

        for line in lines:
            heading_match = HEADING_PATTERN.match(line.strip())
            if heading_match:
                flush()
                hashes, heading = heading_match.groups()
                current_heading = heading.strip()
                current_level = len(hashes)
                continue

            priority_match = re.match(r"\s*priority_score\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$", line, flags=re.IGNORECASE)
            if priority_match:
                priority_score = float(priority_match.group(1))
                continue

            current_lines.append(line)

        flush()
        return chunks

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return [token.lower() for token in TOKEN_PATTERN.findall(text)]

    def iter_chunks(self) -> Iterable[KnowledgeChunk]:
        return tuple(self._chunks)

    def search(self, query: str, *, limit: int = 5, k1: float = 1.5, b: float = 0.75) -> list[SearchHit]:
        tokens = self.tokenize(query)
        if not tokens or not self._chunks:
            return []

        total_docs = len(self._chunks)
        results: list[SearchHit] = []
        unique_terms = list(dict.fromkeys(tokens))

        for index, chunk in enumerate(self._chunks):
            term_freqs = self._term_freqs[index]
            if not term_freqs:
                continue
            doc_length = max(self._doc_lengths[index], 1)
            score = 0.0
            matched_terms: list[str] = []
            for term in unique_terms:
                freq = term_freqs.get(term, 0)
                if freq == 0:
                    continue
                matched_terms.append(term)
                doc_freq = self._doc_freq.get(term, 0)
                idf = log(1 + (total_docs - doc_freq + 0.5) / (doc_freq + 0.5))
                numerator = freq * (k1 + 1)
                denominator = freq + k1 * (1 - b + b * (doc_length / (self._avg_doc_length or 1.0)))
                score += idf * (numerator / denominator)

            if score == 0.0:
                continue

            heading_tokens = set(self.tokenize(chunk.heading))
            heading_boost = 1.2 if any(term in heading_tokens for term in unique_terms) else 1.0
            final_score = score * chunk.priority_score * heading_boost
            results.append(SearchHit(chunk=chunk, score=final_score, terms=matched_terms))

        results.sort(key=lambda hit: hit.score, reverse=True)
        return results[:limit]
