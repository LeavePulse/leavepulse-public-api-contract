from __future__ import annotations

from leavepulse_public_api_contract import (
    ContractOperation,
    PublicApiContract,
    build_docs_manifest,
    build_public_openapi_document,
    generate_java_client_source,
    generate_python_client_source,
    generate_typescript_client_source,
)


def _build_contract() -> PublicApiContract:
    return PublicApiContract(
        title="LeavePulse Developer API",
        version="2026-04-06",
        description="Public API contract.",
        runtime_prefix="/v1",
        canonical_base_url="https://api.leavepulse.com/v1",
        operations=(
            ContractOperation(
                id="list-servers",
                method="get",
                runtime_path="/v1/servers",
                sdk_name="listServers",
                summary="List servers",
                description="Return public servers.",
                auth_kind="public",
                docs_group="servers",
            ),
            ContractOperation(
                id="get-me",
                method="get",
                runtime_path="/v1/me",
                sdk_name="getMe",
                summary="Get me",
                description="Return the current developer principal.",
                auth_kind="bearer",
                docs_group="auth",
            ),
        ),
    )


def _build_source_document() -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "runtime", "version": "dev"},
        "paths": {
            "/v1/servers": {
                "get": {
                    "operationId": "list_servers",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ServerListResponse"
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/v1/me": {
                "get": {
                    "operationId": "get_me",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/DeveloperProfile"
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ServerListResponse": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}}
                    },
                },
                "DeveloperProfile": {
                    "type": "object",
                    "properties": {"username": {"type": "string"}},
                },
                "UnusedSchema": {
                    "type": "object",
                    "properties": {"ignored": {"type": "string"}},
                },
            },
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                }
            },
        },
    }


def test_public_openapi_document_is_canonicalized() -> None:
    document = build_public_openapi_document(
        source_document=_build_source_document(),
        contract=_build_contract(),
    )

    assert document["servers"] == [{"url": "https://api.leavepulse.com/v1"}]
    assert sorted(document["paths"]) == ["/me", "/servers"]
    assert document["paths"]["/servers"]["get"]["security"] == []
    assert document["paths"]["/me"]["get"]["security"] == [
        {"BearerAuth": ["openid"]}
    ]
    assert "UnusedSchema" not in document["components"]["schemas"]


def test_docs_manifest_and_sdk_generation_use_canonical_paths() -> None:
    contract = _build_contract()
    document = build_public_openapi_document(
        source_document=_build_source_document(),
        contract=contract,
    )

    manifest = build_docs_manifest(contract=contract, openapi_url="/v1/openapi.json")
    typescript = generate_typescript_client_source(
        contract=contract,
        openapi_document=document,
    )
    python = generate_python_client_source(
        contract=contract,
        openapi_document=document,
    )
    java = generate_java_client_source(
        contract=contract,
        openapi_document=document,
    )

    assert manifest.canonical_base_url == "https://api.leavepulse.com/v1"
    assert manifest.sections[0].operations[0].path == "/me"
    assert 'normalizeBaseUrl(options.baseUrl ?? "https://api.leavepulse.com/v1")' in typescript
    assert 'return this.request<ResponseFor<"/servers", "get">>("get", "/servers"' in typescript
    assert 'base_url: str = "https://api.leavepulse.com/v1"' in python
    assert 'return self._request("GET", f"/servers", params=params)' in python
    assert 'private String baseUrl = "https://api.leavepulse.com/v1";' in java
    assert 'return request("GET", "/servers", query, null);' in java
