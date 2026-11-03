# -*- coding: utf-8 -*-
"""
可选向量化组件。

项目默认不依赖 faiss / numpy / sentence-transformers：
- 未开启 EMBEDDING_ENABLED 时返回 None，RAG 与语义记忆自动退回 BM25 + 结构化混合检索；
- 开启后，可对接任意 OpenAI 兼容的 /embeddings 服务（如 vLLM 部署 BGE-M3、
  硅基流动、DashScope 兼容模式等），向量以 JSON 存于 PostgreSQL JSONB。

这样既保留方案中「BGE-M3 + 向量库」的升级路径，又不让本地单机部署被重依赖卡住。
"""
from __future__ import annotations

import json
import threading
from typing import List, Optional, Sequence

from ..config import settings

_lock = threading.Lock()
_warned = False


class EmbeddingProvider:
    """OpenAI 兼容 embeddings 客户端（惰性初始化、失败自动降级）"""

    def __init__(self) -> None:
        self.enabled = bool(settings.EMBEDDING_ENABLED)
        self.model = settings.EMBEDDING_MODEL
        self._client = None
        self._broken = False

    def _ensure_client(self):
        if self._client is not None or self._broken:
            return self._client
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if not api_key:
            self._broken = True
            return None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, base_url=settings.EMBEDDING_BASE_URL or None)
        except Exception as exc:  # noqa: BLE001
            self._mark_broken(f"初始化失败: {exc}")
        return self._client

    @staticmethod
    def _mark_broken(reason: str) -> None:
        global _warned
        with _lock:
            if not _warned:
                print(f"[embeddings] 向量模型不可用，自动降级为 BM25 混合检索：{reason}")
                _warned = True

    def embed(self, texts: Sequence[str]) -> Optional[List[List[float]]]:
        """返回向量列表；未启用或失败返回 None"""
        if not self.enabled or not texts:
            return None
        client = self._ensure_client()
        if client is None:
            return None
        try:
            resp = client.embeddings.create(model=self.model, input=list(texts))
            vectors = [list(item.embedding) for item in resp.data]
            if not vectors or not vectors[0]:
                return None
            return vectors
        except Exception as exc:  # noqa: BLE001
            self._mark_broken(str(exc)[:160])
            return None

    def embed_one(self, text: str) -> Optional[List[float]]:
        vectors = self.embed([text])
        return vectors[0] if vectors else None


provider = EmbeddingProvider()


def dumps(vector: Optional[Sequence[float]]) -> Optional[str]:
    return json.dumps(list(vector)) if vector else None


def loads(raw) -> Optional[List[float]]:
    if not raw:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    try:
        value = json.loads(raw)
        return [float(x) for x in value] if value else None
    except (TypeError, ValueError):
        return None
