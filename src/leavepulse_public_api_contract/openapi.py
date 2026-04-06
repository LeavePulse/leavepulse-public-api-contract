from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import ContractOperation, PublicApiContract


def canonical_path_for_operation(
    operation: ContractOperation,
    *,
    contract: PublicApiContract,
) -> str:
    runtime_path = operation.runtime_path
    prefix = contract.runtime_prefix.rstrip("/")
    if runtime_path == prefix:
        return "/"
    if runtime_path.startswith(f"{prefix}/"):
        return runtime_path[len(prefix) :]
    return runtime_path


def _collect_refs(value: Any, refs: set[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/"):
            parts = ref.split("/")
            if len(parts) == 4:
                refs.add((parts[2], parts[3]))
        for child in value.values():
            _collect_refs(child, refs)
        return

    if isinstance(value, list):
        for child in value:
            _collect_refs(child, refs)


def _build_filtered_components(
    source_components: dict[str, Any],
    paths: dict[str, Any],
) -> dict[str, Any]:
    collected: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    root_refs: set[tuple[str, str]] = set()
    _collect_refs(paths, root_refs)
    pending.extend(sorted(root_refs))

    while pending:
        section, name = pending.pop()
        key = (section, name)
        if key in seen:
            continue
        seen.add(key)

        section_payload = source_components.get(section)
        if not isinstance(section_payload, dict):
            continue

        item = section_payload.get(name)
        if item is None:
            continue

        collected.setdefault(section, {})[name] = item

        nested_refs: set[tuple[str, str]] = set()
        _collect_refs(item, nested_refs)
        pending.extend(sorted(nested_refs))

    security_schemes = source_components.get("securitySchemes")
    if isinstance(security_schemes, dict) and security_schemes:
        collected["securitySchemes"] = security_schemes

    return collected


def _operation_security(auth_kind: str) -> list[dict[str, list[str]]]:
    if auth_kind == "public":
        return []
    if auth_kind == "bearer":
        return [{"BearerAuth": ["openid"]}]
    return [{}, {"BearerAuth": ["openid"]}]


def build_public_openapi_document(
    *,
    source_document: dict[str, Any],
    contract: PublicApiContract,
) -> dict[str, Any]:
    source_paths = source_document.get("paths", {})
    generated_paths: dict[str, dict[str, Any]] = {}

    for operation in contract.operations:
        source_path_item = source_paths.get(operation.runtime_path)
        if not isinstance(source_path_item, dict):
            msg = f"Contract path is missing from runtime OpenAPI: {operation.runtime_path}"
            raise KeyError(msg)

        source_operation = source_path_item.get(operation.method)
        if not isinstance(source_operation, dict):
            msg = (
                "Contract operation is missing from runtime OpenAPI: "
                f"{operation.method.upper()} {operation.runtime_path}"
            )
            raise KeyError(msg)

        canonical_path = canonical_path_for_operation(operation, contract=contract)
        generated_operation = deepcopy(source_operation)
        generated_operation["summary"] = operation.summary
        generated_operation["description"] = operation.description
        generated_operation["tags"] = list(operation.tags)
        generated_operation["security"] = _operation_security(operation.auth_kind)

        generated_paths.setdefault(canonical_path, {})[operation.method] = generated_operation

    components = _build_filtered_components(
        source_components=source_document.get("components", {}),
        paths=generated_paths,
    )

    return {
        "openapi": source_document.get("openapi", "3.1.0"),
        "info": {
            "title": contract.title,
            "version": contract.version,
            "description": contract.description,
        },
        "servers": [{"url": contract.canonical_base_url}],
        "paths": generated_paths,
        "components": components,
    }
