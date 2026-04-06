from __future__ import annotations

from typing import Literal

import msgspec

AuthKind = Literal["public", "mixed", "bearer"]
HttpMethod = Literal["get", "post", "put", "patch", "delete"]


class ContractOperation(msgspec.Struct, kw_only=True, frozen=True):
    id: str
    method: HttpMethod
    runtime_path: str
    sdk_name: str | None
    summary: str
    description: str
    auth_kind: AuthKind
    docs_group: str
    include_in_sdk: bool = True
    tags: tuple[str, ...] = ("Developer API",)


class PublicApiContract(msgspec.Struct, kw_only=True, frozen=True):
    title: str
    version: str
    description: str
    runtime_prefix: str
    canonical_base_url: str
    operations: tuple[ContractOperation, ...]


class DocsOperation(msgspec.Struct, kw_only=True, frozen=True):
    id: str
    method: str
    path: str
    summary: str
    description: str
    auth_kind: AuthKind


class DocsSection(msgspec.Struct, kw_only=True, frozen=True):
    id: str
    title: str
    description: str
    operations: tuple[DocsOperation, ...]


class DocsManifest(msgspec.Struct, kw_only=True, frozen=True):
    title: str
    description: str
    canonical_base_url: str
    openapi_url: str
    auth_scheme: str
    sdk_languages: tuple[str, ...]
    sections: tuple[DocsSection, ...]
