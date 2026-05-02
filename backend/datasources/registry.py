"""DataSourceRegistry — loads source specs from YAML, builds resolvers, persists user-added sources.

Implements the framework's KnowledgeResolverRegistry Protocol. Looks up by id
(source-first), with `resolver_for(ontology_type, source_hint)` provided for
the framework's own callers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from tcs_hitl_context import KnowledgeFact, KnowledgeResolver

from .csv_source import CsvResolver
from .http_source import HttpResolver
from .postgres_source import PostgresResolver
from .sqlite_source import SqliteResolver
from .vector_source import VectorStoreResolver

log = logging.getLogger(__name__)


class ResolverError(Exception):
    pass


@dataclass
class DataSourceSpec:
    """Stored representation of a source — what gets serialised to sources.yaml."""

    id: str
    kind: str   # csv | sqlite | http | postgres | vector_store
    config: dict[str, Any] = field(default_factory=dict)
    default: bool = False  # if True, can't be deleted via the API
    description: str = ""

    def to_yaml(self) -> dict[str, Any]:
        out = {"id": self.id, "kind": self.kind, **self.config}
        if self.default:
            out["default"] = True
        if self.description:
            out["description"] = self.description
        return out


class DataSourceRegistry:
    """Holds resolvers in memory, persists specs to disk."""

    def __init__(self, storage_path: Path, project_root: Path):
        self._storage_path = storage_path
        self._project_root = project_root
        self._specs: dict[str, DataSourceSpec] = {}
        self._resolvers: dict[str, KnowledgeResolver] = {}
        # Embedding credentials passed through to vector resolvers. One of:
        #   _openai_api_key            — public OpenAI
        #   _azure_embedding_config    — {api_key, endpoint, api_version, deployment}
        # Azure wins when both are set (operator on Azure usually means *only* Azure).
        self._openai_api_key: Optional[str] = None
        self._azure_embedding_config: Optional[dict] = None
        # Set by AppState wiring so register/remove can sync auto-scenarios.
        # Optional and lazy-imported to avoid a circular dep at module load.
        self._on_register_callback: Optional[Any] = None
        self._on_remove_callback: Optional[Any] = None

    def set_lifecycle_hooks(self, *, on_register: Any, on_remove: Any) -> None:
        """Wire callbacks so auto-scenarios stay in sync with sources.

        `on_register(spec)` runs after a non-default source registers.
        `on_remove(source_id)` runs when a non-default source is removed.
        """
        self._on_register_callback = on_register
        self._on_remove_callback = on_remove

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    @classmethod
    def from_yaml(
        cls,
        storage_path: Path,
        project_root: Path,
        openai_api_key: Optional[str] = None,
        azure_embedding_config: Optional[dict] = None,
    ) -> "DataSourceRegistry":
        reg = cls(storage_path=storage_path, project_root=project_root)
        reg._openai_api_key = openai_api_key
        reg._azure_embedding_config = azure_embedding_config
        if storage_path.exists():
            data = yaml.safe_load(storage_path.read_text()) or {}
            for entry in data.get("sources", []):
                spec_id = entry.pop("id")
                spec_kind = entry.pop("kind")
                is_default = bool(entry.pop("default", False))
                description = str(entry.pop("description", ""))
                spec = DataSourceSpec(
                    id=spec_id,
                    kind=spec_kind,
                    config=entry,
                    default=is_default,
                    description=description,
                )
                try:
                    reg.register(spec, persist=False)
                except Exception as exc:  # noqa: BLE001
                    log.warning("failed to register source %s: %s", spec.id, exc)
        return reg

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"sources": [s.to_yaml() for s in self._specs.values()]}
        self._storage_path.write_text(yaml.safe_dump(data, sort_keys=False))

    # -------------------------------------------------------------------------
    # Build a resolver from a spec
    # -------------------------------------------------------------------------
    def _build(self, spec: DataSourceSpec) -> KnowledgeResolver:
        cfg = spec.config
        if spec.kind == "csv":
            return CsvResolver(
                source_id=spec.id,
                path=self._resolve_path(cfg["path"]),
                ontology_type=cfg.get("ontology_type", "Record"),
                id_field=cfg.get("id_field", "id"),
                title_field=cfg.get("title_field", "name"),
                summary_template=cfg.get("summary_template", ""),
            )
        if spec.kind == "sqlite":
            return SqliteResolver(
                source_id=spec.id,
                path=self._resolve_path(cfg["path"]),
                queries=cfg.get("queries", {}),
                sample_filter=cfg.get("sample_filter"),
            )
        if spec.kind == "http":
            return HttpResolver(
                source_id=spec.id,
                base_url=cfg["base_url"],
                paths=cfg.get("paths", {}),
                headers=cfg.get("headers"),
            )
        if spec.kind == "postgres":
            return PostgresResolver(
                source_id=spec.id,
                dsn=cfg["dsn"],
                queries=cfg.get("queries", {}),
                sample_filter=cfg.get("sample_filter"),
            )
        if spec.kind == "vector_store":
            return VectorStoreResolver(
                source_id=spec.id,
                folder=self._resolve_path(cfg["folder"]),
                index_path=self._resolve_path(cfg["index_path"]),
                ontology_type=cfg.get("ontology_type", "PolicyExcerpt"),
                top_k=int(cfg.get("top_k", 3)),
                embed_model=cfg.get("embed_model", "text-embedding-3-small"),
                openai_api_key=self._openai_api_key,
                azure_config=self._azure_embedding_config,
            )
        raise ResolverError(f"unknown source kind: {spec.kind!r}")

    def _resolve_path(self, raw: str) -> Path:
        # Defensive: strip whitespace from the path so accidental tabs/spaces
        # from copy-paste don't break file resolution.
        p = Path((raw or "").strip())
        return p if p.is_absolute() else (self._project_root / p)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def register(self, spec: DataSourceSpec, *, persist: bool = True) -> KnowledgeResolver:
        # Defensive: strip whitespace from any user-typed strings so accidental
        # tabs/spaces from copy-paste don't break lookups or break file paths.
        spec.id = spec.id.strip() if spec.id else spec.id
        if not spec.id:
            raise ResolverError("source id cannot be empty")
        for path_field in ("path", "folder", "index_path", "base_url", "dsn"):
            v = spec.config.get(path_field)
            if isinstance(v, str):
                spec.config[path_field] = v.strip()
        if spec.id in self._specs:
            raise ResolverError(f"source {spec.id!r} already registered")
        resolver = self._build(spec)
        self._specs[spec.id] = spec
        self._resolvers[spec.id] = resolver
        if persist:
            self._save()
        # Auto-scenarios are only created for non-default (operator-registered)
        # sources — defaults already have hand-authored scenarios where needed.
        if not spec.default and self._on_register_callback is not None:
            try:
                self._on_register_callback(spec)
            except Exception as exc:  # noqa: BLE001
                log.warning("auto-scenario hook for %s failed: %s", spec.id, exc)
        return resolver

    def remove(self, source_id: str) -> None:
        spec = self._specs.get(source_id)
        if spec is None:
            raise ResolverError(f"unknown source {source_id!r}")
        if spec.default:
            raise ResolverError(f"cannot delete default source {source_id!r}")
        self._specs.pop(source_id, None)
        self._resolvers.pop(source_id, None)
        self._save()
        if self._on_remove_callback is not None:
            try:
                self._on_remove_callback(source_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("auto-scenario cleanup for %s failed: %s", source_id, exc)

    def get(self, source_id: str) -> Optional[KnowledgeResolver]:
        return self._resolvers.get(source_id)

    def require(self, source_id: str) -> KnowledgeResolver:
        r = self.get(source_id)
        if r is None:
            raise ResolverError(f"unknown source {source_id!r}")
        return r

    def specs(self) -> list[DataSourceSpec]:
        return list(self._specs.values())

    def all(self) -> list[KnowledgeResolver]:
        return list(self._resolvers.values())

    def sample(self, source_id: str, n: int = 3) -> list[KnowledgeFact]:
        r = self.require(source_id)
        # All concrete resolvers expose a `.sample()`; framework Protocol doesn't
        # require it but we treat it as part of our internal contract.
        if hasattr(r, "sample"):
            return r.sample(n)  # type: ignore[no-any-return]
        return []

    # -------------------------------------------------------------------------
    # Framework Protocol (KnowledgeResolverRegistry)
    # -------------------------------------------------------------------------
    def resolver_for(
        self, ontology_type: str, source_hint: Optional[str] = None
    ) -> KnowledgeResolver:
        if source_hint:
            return self.require(source_hint)
        # Fallback: return the first resolver that can handle this ontology type.
        # We don't track ontology type → resolver here; binders pass source_hint.
        for r in self._resolvers.values():
            return r
        raise ResolverError("no resolvers registered")
