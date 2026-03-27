# PageIndex builder and pageindex_query. Spec 05; plan Phase 3.
# LLM summarization: traverse section hierarchy and generate 2-3 sentence summaries per section.

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.models import LDU, LDUContentType, PageIndex, PageIndexSection

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 3
DEFAULT_PAGEINDEX_DIR = ".refinery/pageindex"
CHUNK_TYPE_TO_DATA_TYPE: dict[str, str] = {
    LDUContentType.TABLE.value: "tables",
    LDUContentType.TABLE_SECTION.value: "tables",
    LDUContentType.FIGURE.value: "figures",
    LDUContentType.LIST.value: "lists",
    LDUContentType.PARAGRAPH.value: "paragraphs",
    LDUContentType.SECTION_INTRO.value: "paragraphs",
    LDUContentType.SECTION_HEADER.value: "paragraphs",
    LDUContentType.HEADING.value: "paragraphs",
    LDUContentType.FOOTNOTE.value: "other",
    LDUContentType.OTHER.value: "other",
}


class SectionSummarizer(Protocol):
    def summarize(self, title: str, content: str, section_id: str, document_id: str) -> str | None:
        ...


class StubSummarizer:
    def summarize(self, title: str, content: str, section_id: str, document_id: str) -> str | None:
        return None


def _load_dotenv() -> None:
    """Load .env from cwd or project root (same as vision extractor)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        env_file = base / ".env"
        if not env_file.is_file():
            continue
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
        except OSError:
            pass
        break


_PROVIDER_DEFAULT_KEY_ENVS: dict[str, str] = {
    "google": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_PROVIDER_BASE_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com",
}

_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
    "openrouter": "gpt-4o-mini",
    "google": "gemini-1.5-flash",
}


class LLMSummarizer:
    """Generate 2-3 sentence section summaries via LLM. Uses REFINERY_VISION_PROVIDER (openai, deepseek, openrouter, google)."""

    def summarize(self, title: str, content: str, section_id: str, document_id: str) -> str | None:
        if not (content or "").strip():
            return None
        _load_dotenv()
        provider = (os.environ.get("REFINERY_VISION_PROVIDER", "") or "openai").strip().lower()
        default_api_key_env = _PROVIDER_DEFAULT_KEY_ENVS.get(provider, "OPENAI_API_KEY")
        api_key_env = os.environ.get("REFINERY_VISION_API_KEY_ENV", default_api_key_env)
        api_key = (os.environ.get("REFINERY_VISION_API_KEY") or os.environ.get(api_key_env, "")).strip()
        if not api_key:
            logger.debug("LLMSummarizer: no API key configured for provider=%s", provider)
            return None
        prompt = (
            "Summarize this document section in 2-3 concise sentences. "
            "Capture the main topic and key points. Title: %s\n\nContent: %s"
        ) % (title[:200], (content or "")[:3000])
        try:
            if provider == "google":
                return self._summarize_google(prompt, api_key, section_id)
            else:
                # openai, deepseek, openrouter — all use the OpenAI-compatible client.
                # Unknown providers also fall here; _PROVIDER_BASE_URLS controls routing.
                return self._summarize_openai(prompt, api_key, section_id, provider=provider)
        except Exception as e:
            logger.warning("LLMSummarizer failed for %s: %s", section_id, e)
            return None

    def _summarize_openai(self, prompt: str, api_key: str, section_id: str, provider: str = "openai") -> str | None:
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("LLMSummarizer: openai not installed (uv add openai)")
            return None
        base_url = _PROVIDER_BASE_URLS.get(provider)
        client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        model = (
            os.environ.get("REFINERY_LLM_MODEL")
            or _PROVIDER_DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.3,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text if text else None

    def _summarize_google(self, prompt: str, api_key: str, section_id: str) -> str | None:
        try:
            import google.generativeai as genai
        except ImportError:
            logger.warning("LLMSummarizer: google-generativeai not installed (uv add google-generativeai)")
            return None
        genai.configure(api_key=api_key)
        model_name = os.environ.get("REFINERY_LLM_MODEL") or _PROVIDER_DEFAULT_MODELS["google"]
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(max_output_tokens=150))
        text = getattr(resp, "text", None) or ""
        return text.strip() if text else None


def get_default_summarizer() -> SectionSummarizer:
    """Return LLM summarizer when REFINERY_VISION_PROVIDER and an API key are configured, else StubSummarizer."""
    _load_dotenv()
    provider = (os.environ.get("REFINERY_VISION_PROVIDER", "") or "").strip().lower()
    default_api_key_env = _PROVIDER_DEFAULT_KEY_ENVS.get(provider, "OPENAI_API_KEY")
    api_key_env_name = os.environ.get("REFINERY_VISION_API_KEY_ENV", default_api_key_env)
    api_key = (os.environ.get("REFINERY_VISION_API_KEY") or os.environ.get(api_key_env_name, "")).strip()
    if provider and api_key:
        return LLMSummarizer()
    return StubSummarizer()


class CachedSummarizer:
    def __init__(self, delegate: SectionSummarizer) -> None:
        self._delegate = delegate
        self._cache: dict[tuple[str, str], str | None] = {}

    def summarize(self, title: str, content: str, section_id: str, document_id: str) -> str | None:
        key = (document_id, section_id)
        if key in self._cache:
            return self._cache[key]
        out = self._delegate.summarize(title, content, section_id, document_id)
        self._cache[key] = out
        return out


def _first_page(ldu: LDU) -> int:
    if not ldu.page_refs:
        return 1
    return ldu.page_refs[0].page_number


def _last_page(ldu: LDU) -> int:
    if not ldu.page_refs:
        return 1
    return ldu.page_refs[-1].page_number


def _heading_level(title: str) -> int:
    m = re.match(r"^(\d+(?:\.\d+)*)\.?\s*", title.strip())
    if not m:
        return 1
    return m.group(1).count(".") + 1


def _data_types_from_ldus(ldu_ids: list[str], ldus_by_id: dict[str, LDU]) -> list[str]:
    seen: set[str] = set()
    for lid in ldu_ids:
        ldu = ldus_by_id.get(lid)
        if not ldu:
            continue
        dt = CHUNK_TYPE_TO_DATA_TYPE.get(ldu.content_type.value, "other")
        seen.add(dt)
    return sorted(seen)


def build_page_index(
    ldus: list[LDU],
    document_id: str,
    page_count: int,
    *,
    summarizer: SectionSummarizer | None = None,
    max_summary_content_chars: int = 2000,
) -> PageIndex:
    summarizer = summarizer or StubSummarizer()
    ldus_by_id = {ldu.id: ldu for ldu in ldus}
    if not ldus:
        root = PageIndexSection(
            id="root",
            document_id=document_id,
            title="Document",
            level=0,
            page_start=1,
            page_end=page_count,
            child_sections=[],
            key_entities=[],
            summary=None,
            data_types_present=[],
            ldu_ids=[],
        )
        return PageIndex(document_id=document_id, page_count=page_count, root=root, built_at=datetime.now(timezone.utc))

    heading_types = (LDUContentType.HEADING, LDUContentType.SECTION_HEADER, LDUContentType.SECTION_INTRO)
    headings: list[tuple[int, str, int, int]] = []
    for i, ldu in enumerate(ldus):
        if ldu.content_type in heading_types:
            title = (ldu.text or "").strip() or f"Section {len(headings) + 1}"
            level = _heading_level(title)
            first_page = _first_page(ldu)
            headings.append((level, title, first_page, i))

    if not headings:
        all_ids = [ldu.id for ldu in ldus]
        data_types = _data_types_from_ldus(all_ids, ldus_by_id)
        root = PageIndexSection(
            id="root",
            document_id=document_id,
            title="Document",
            level=0,
            page_start=1,
            page_end=page_count,
            child_sections=[],
            key_entities=[],
            summary=None,
            data_types_present=data_types,
            ldu_ids=all_ids,
        )
        return PageIndex(document_id=document_id, page_count=page_count, root=root, built_at=datetime.now(timezone.utc))

    sections: list[tuple[int, str, int, int, list[int]]] = []
    for h_idx, (level, title, page_start, ldu_idx) in enumerate(headings):
        page_end = page_count
        end_ldu_idx = len(ldus)
        for j in range(h_idx + 1, len(headings)):
            next_level, _, next_page, next_ldu_idx = headings[j]
            if next_level <= level:
                page_end = min(page_end, next_page - 1 if next_page > 1 else 1)
                end_ldu_idx = next_ldu_idx
                break
        if page_end < page_start:
            page_end = page_start
        indices = []
        for k in range(ldu_idx, end_ldu_idx):
            ldu = ldus[k]
            fp, lp = _first_page(ldu), _last_page(ldu)
            if fp <= page_end and lp >= page_start:
                indices.append(k)
        sections.append((level, title, page_start, page_end, indices))

    child_sections_list: list[PageIndexSection] = []
    for idx, (level, title, page_start, page_end, ldu_indices) in enumerate(sections):
        ldu_ids_sec = [ldus[i].id for i in ldu_indices]
        data_types = _data_types_from_ldus(ldu_ids_sec, ldus_by_id)
        content_for_summary = " ".join((ldus[i].text or "").strip() for i in ldu_indices[:20])[:max_summary_content_chars]
        try:
            summary = summarizer.summarize(title, content_for_summary, f"sec_{idx}", document_id)
        except Exception as e:
            logger.warning("Summarizer failed for section %s: %s", title, e)
            summary = None
        child_sections_list.append(
            PageIndexSection(
                id=f"sec_{idx}",
                document_id=document_id,
                title=title,
                level=min(level, 1),
                page_start=page_start,
                page_end=page_end,
                child_sections=[],
                key_entities=[],
                summary=summary,
                data_types_present=data_types,
                ldu_ids=ldu_ids_sec,
            )
        )

    root = PageIndexSection(
        id="root",
        document_id=document_id,
        title="Document",
        level=0,
        page_start=1,
        page_end=page_count,
        child_sections=child_sections_list,
        key_entities=[],
        summary=None,
        data_types_present=_data_types_from_ldus([ldu.id for ldu in ldus], ldus_by_id),
        ldu_ids=[ldu.id for ldu in ldus],
    )
    return PageIndex(document_id=document_id, page_count=page_count, root=root, built_at=datetime.now(timezone.utc))


def write_pageindex(page_index: PageIndex, base_dir: str | Path = DEFAULT_PAGEINDEX_DIR) -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{page_index.document_id}.json"
    payload = _pageindex_to_json_serializable(page_index)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def _pageindex_to_json_serializable(pi: PageIndex) -> dict:
    built_at = pi.built_at.isoformat() if pi.built_at else None
    return {
        "document_id": pi.document_id,
        "page_count": pi.page_count,
        "root": _section_to_dict(pi.root),
        "built_at": built_at,
    }


def _section_to_dict(s: PageIndexSection) -> dict:
    return {
        "id": s.id,
        "document_id": s.document_id,
        "title": s.title,
        "level": s.level,
        "page_start": s.page_start,
        "page_end": s.page_end,
        "child_sections": [_section_to_dict(c) for c in s.child_sections],
        "key_entities": s.key_entities,
        "summary": s.summary,
        "data_types_present": s.data_types_present,
        "ldu_ids": s.ldu_ids,
    }


def load_pageindex(path: str | Path) -> PageIndex:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return _pageindex_from_dict(data)


def _pageindex_from_dict(data: dict) -> PageIndex:
    root_data = data["root"]
    root = _section_from_dict(root_data)
    return PageIndex(
        document_id=data["document_id"],
        page_count=data["page_count"],
        root=root,
        built_at=datetime.fromisoformat(data["built_at"].replace("Z", "+00:00")) if data.get("built_at") else None,
    )


def _section_from_dict(d: dict) -> PageIndexSection:
    children = [_section_from_dict(c) for c in d.get("child_sections", [])]
    return PageIndexSection(
        id=d["id"],
        document_id=d["document_id"],
        title=d.get("title", ""),
        level=d.get("level", 0),
        page_start=d["page_start"],
        page_end=d["page_end"],
        child_sections=children,
        key_entities=d.get("key_entities", []),
        summary=d.get("summary"),
        data_types_present=d.get("data_types_present", []),
        ldu_ids=d.get("ldu_ids", []),
    )


def _embedding_similarity(topic: str, section_text: str) -> float | None:
    """Return cosine similarity (0-1) when semantic embeddings available, else None."""
    if not (topic or section_text).strip():
        return None
    try:
        from src.data.vector_store import get_embedding_function
        fn = get_embedding_function()
        name = getattr(fn, "name", None)
        if callable(name) and name() == "deterministic":
            return None
        emb = fn.embed_query(topic)
        sec_emb = fn.embed_query(section_text)
        if not emb or not sec_emb or len(emb[0]) != len(sec_emb[0]):
            return None
        a, b = emb[0], sec_emb[0]
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na <= 0 or nb <= 0:
            return None
        sim = dot / (na * nb)
        return max(0.0, min(1.0, (sim + 1) / 2))
    except Exception:
        return None


def _score_section(section: PageIndexSection, topic: str, topic_lower: str, topic_tokens: set[str]) -> float:
    score = 0.0
    title_lower = (section.title or "").lower()
    if topic_lower in title_lower:
        score += 10.0
    for t in topic_tokens:
        if t in title_lower:
            score += 3.0
    if section.summary:
        summary_lower = section.summary.lower()
        if topic_lower in summary_lower:
            score += 5.0
        for t in topic_tokens:
            if t in summary_lower:
                score += 1.0
    for e in section.key_entities:
        if topic_lower in e.lower() or any(t in e.lower() for t in topic_tokens):
            score += 2.0
    for dt in section.data_types_present:
        if topic_lower in dt or any(t in dt for t in topic_tokens):
            score += 1.0
    # Semantic boost when embeddings available (title + summary)
    section_text = f"{(section.title or '')} {(section.summary or '')}".strip()
    emb_sim = _embedding_similarity(topic, section_text)
    if emb_sim is not None:
        score += emb_sim * 15.0
    return score


def _collect_sections_for_query(root: PageIndexSection) -> list[PageIndexSection]:
    out: list[PageIndexSection] = []
    for c in root.child_sections:
        out.append(c)
        out.extend(_collect_sections_for_query(c))
    return out


def pageindex_query(
    topic: str,
    page_index: PageIndex | None = None,
    path: str | Path | None = None,
    document_id: str | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> list[PageIndexSection]:
    if page_index is None and path is None:
        raise ValueError("Provide page_index or path")
    if page_index is None:
        page_index = load_pageindex(path)
    if document_id and page_index.document_id != document_id:
        return []
    sections = _collect_sections_for_query(page_index.root)
    topic_stripped = topic.strip()
    topic_lower = topic_stripped.lower()
    topic_tokens = {w for w in re.split(r"\W+", topic_lower) if len(w) > 1}
    scored = [(s, _score_section(s, topic_stripped, topic_lower, topic_tokens)) for s in sections]
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:top_n]]


__all__ = [
    "SectionSummarizer",
    "StubSummarizer",
    "LLMSummarizer",
    "get_default_summarizer",
    "CachedSummarizer",
    "build_page_index",
    "write_pageindex",
    "load_pageindex",
    "pageindex_query",
    "DEFAULT_TOP_N",
    "DEFAULT_PAGEINDEX_DIR",
]
