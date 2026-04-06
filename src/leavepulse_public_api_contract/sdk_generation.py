from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .models import ContractOperation, PublicApiContract
from .openapi import canonical_path_for_operation

_PATH_PARAM_PATTERN = re.compile(r"{([^}]+)}")


def _to_camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _to_pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _path_parameters(operation: ContractOperation) -> tuple[str, ...]:
    return tuple(_PATH_PARAM_PATTERN.findall(operation.runtime_path))


def _operation_payload(
    *,
    openapi_document: dict[str, Any],
    contract: PublicApiContract,
    operation: ContractOperation,
) -> dict[str, Any]:
    canonical_path = canonical_path_for_operation(operation, contract=contract)
    path_item = openapi_document["paths"][canonical_path]
    return path_item[operation.method]


def _query_parameters(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = []
    for parameter in payload.get("parameters", []):
        if parameter.get("in") == "query":
            items.append(parameter)
    return tuple(items)


def _path_parameter_types(payload: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for parameter in payload.get("parameters", []):
        if parameter.get("in") != "path":
            continue
        name = str(parameter["name"])
        schema = parameter.get("schema", {})
        if schema.get("type") == "integer":
            resolved[name] = "int"
        else:
            resolved[name] = "str"
    return resolved


def _resolve_schema(
    *,
    openapi_document: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    if not schema:
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        return openapi_document["components"]["schemas"][name]
    return schema


def _request_body_schema(
    *,
    openapi_document: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    request_body = payload.get("requestBody")
    if not isinstance(request_body, dict):
        return {}
    content = request_body.get("content", {})
    json_schema = content.get("application/json", {}).get("schema")
    if not isinstance(json_schema, dict):
        return {}
    return _resolve_schema(openapi_document=openapi_document, schema=json_schema)


def _schema_type_to_python(schema: dict[str, Any], *, required: bool) -> str:
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        non_null = [item for item in one_of if item.get("type") != "null"]
        if len(non_null) == 1:
            return _schema_type_to_python(non_null[0], required=False)
    schema_type = schema.get("type")
    if schema_type == "integer":
        base = "int"
    elif schema_type == "boolean":
        base = "bool"
    elif schema_type == "array":
        item_schema = schema.get("items", {})
        item_type = _schema_type_to_python(item_schema, required=True)
        base = f"list[{item_type}]"
    else:
        base = "str"
    return base if required else f"{base} | None"


def _schema_type_to_java(schema: dict[str, Any], *, required: bool) -> str:
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        non_null = [item for item in one_of if item.get("type") != "null"]
        if len(non_null) == 1:
            return _schema_type_to_java(non_null[0], required=False)
    schema_type = schema.get("type")
    if schema_type == "integer":
        return "int" if required else "Integer"
    if schema_type == "boolean":
        return "boolean" if required else "Boolean"
    if schema_type == "array":
        item_schema = schema.get("items", {})
        item_type = _schema_type_to_java(item_schema, required=True)
        return f"List<{item_type}>"
    return "String"


def _body_fields(
    *,
    openapi_document: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any], bool], ...]:
    schema = _request_body_schema(openapi_document=openapi_document, payload=payload)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: list[tuple[str, dict[str, Any], bool]] = []
    for name, field_schema in properties.items():
        if isinstance(field_schema, dict):
            fields.append((str(name), field_schema, name in required))
    fields.sort(key=lambda item: (not item[2], item[0]))
    return tuple(fields)


def _emit_ts_path_expression(path: str) -> str:
    parts = path.split("/")
    if not _PATH_PARAM_PATTERN.search(path):
        return json.dumps(path)

    rendered: list[str] = []
    for part in parts:
        if not part:
            continue
        match = _PATH_PARAM_PATTERN.fullmatch(part)
        if match:
            variable = _to_camel_case(match.group(1))
            rendered.append(f"${{encodeURIComponent(String({variable}))}}")
        else:
            rendered.append(part)
    return f"`/{'/'.join(rendered)}`"


def _render_python_path_expression(path: str) -> str:
    rendered = path
    for param in _PATH_PARAM_PATTERN.findall(path):
        rendered = rendered.replace(
            f"{{{param}}}",
            "{_encode_ref(str(" + _to_camel_case(param) + "))}",
        )
    return rendered


def _render_java_path_expression(path: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _PATH_PARAM_PATTERN.finditer(path):
        literal = path[cursor : match.start()]
        if literal:
            parts.append(json.dumps(literal))
        parts.append(f"encode({_to_camel_case(match.group(1))})")
        cursor = match.end()

    tail = path[cursor:]
    if tail:
        parts.append(json.dumps(tail))

    if not parts:
        return json.dumps(path)
    return " + ".join(parts)


def generate_typescript_client_source(
    *,
    contract: PublicApiContract,
    openapi_document: dict[str, Any],
) -> str:
    operations = [operation for operation in contract.operations if operation.include_in_sdk]
    lines = [
        'import type { paths } from "./generated/openapi"',
        "",
        'type HttpMethod = "get" | "post" | "put" | "patch" | "delete"',
        'type JsonContent<T> = T extends { content: { "application/json": infer R } } ? R : never',
        "type ResponseFor<",
        "  TPath extends keyof paths,",
        "  TMethod extends keyof paths[TPath],",
        "> = paths[TPath][TMethod] extends { responses: infer TResponses }",
        "  ? TResponses extends Record<number, unknown>",
        "    ? 200 extends keyof TResponses",
        "      ? JsonContent<TResponses[200]>",
        "      : 201 extends keyof TResponses",
        "        ? JsonContent<TResponses[201]>",
        "        : 202 extends keyof TResponses",
        "          ? JsonContent<TResponses[202]>",
        "          : never",
        "    : never",
        "  : never",
        "type QueryFor<",
        "  TPath extends keyof paths,",
        "  TMethod extends keyof paths[TPath],",
        '> = paths[TPath][TMethod] extends { parameters: { query?: infer TQuery } } ? TQuery : never',
        "type BodyFor<",
        "  TPath extends keyof paths,",
        "  TMethod extends keyof paths[TPath],",
        '> = paths[TPath][TMethod] extends { requestBody: { content: { "application/json": infer TBody } } }',
        "  ? TBody",
        "  : never",
        "",
        "function normalizeBaseUrl(value: string): string {",
        "  const url = new URL(value)",
        "  const pathname = url.pathname.replace(/\\/+$/, \"\")",
        "  url.pathname = !pathname || pathname === \"/\" ? \"/v1\" : pathname",
        "  url.search = \"\"",
        "  url.hash = \"\"",
        "  return url.toString().replace(/\\/+$/, \"\")",
        "}",
        "",
        "export interface LeavePulseClientOptions {",
        "  baseUrl?: string",
        "  token?: string | null",
        "  fetch?: typeof fetch",
        "}",
        "",
        "export class LeavePulseError extends Error {",
        "  readonly status: number",
        "  readonly body: unknown",
        "",
        "  constructor(message: string, status: number, body: unknown) {",
        "    super(message)",
        '    this.name = "LeavePulseError"',
        "    this.status = status",
        "    this.body = body",
        "  }",
        "}",
        "",
        "export class LeavePulseClient {",
        "  private readonly baseUrl: string",
        "  private readonly token: string | null",
        "  private readonly fetchImpl: typeof fetch",
        "",
        "  constructor(options: LeavePulseClientOptions = {}) {",
        '    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? "https://api.leavepulse.com/v1")',
        "    this.token = options.token ?? null",
        "    this.fetchImpl = options.fetch ?? fetch",
        "  }",
        "",
        "  private buildUrl(path: string, query?: Record<string, unknown>): string {",
        "    const url = new URL(`${this.baseUrl}${path}`)",
        "    if (!query) {",
        "      return url.toString()",
        "    }",
        "",
        "    for (const [key, value] of Object.entries(query)) {",
        "      if (value === undefined || value === null || value === \"\") {",
        "        continue",
        "      }",
        "      if (Array.isArray(value)) {",
        "        for (const entry of value) {",
        "          if (entry !== undefined && entry !== null) {",
        "            url.searchParams.append(key, String(entry))",
        "          }",
        "        }",
        "        continue",
        "      }",
        "      url.searchParams.set(key, String(value))",
        "    }",
        "    return url.toString()",
        "  }",
        "",
        "  private async request<T>(",
        "    method: HttpMethod,",
        "    path: string,",
        "    query?: Record<string, unknown>,",
        "    body?: unknown,",
        "  ): Promise<T> {",
        "    const headers = new Headers()",
        "    if (this.token) {",
        "      headers.set(\"Authorization\", `Bearer ${this.token}`)",
        "    }",
        "    if (body !== undefined) {",
        "      headers.set(\"Content-Type\", \"application/json\")",
        "    }",
        "",
        "    const response = await this.fetchImpl(this.buildUrl(path, query), {",
        "      method: method.toUpperCase(),",
        "      headers,",
        "      body: body === undefined ? undefined : JSON.stringify(body),",
        "    })",
        "",
        "    const text = await response.text()",
        "    const payload = text ? JSON.parse(text) : null",
        "    if (!response.ok) {",
        "      const detail =",
        "        typeof payload === \"object\" && payload && \"detail\" in payload",
        "          ? String((payload as { detail?: unknown }).detail ?? \"\")",
        "          : response.statusText",
        "      throw new LeavePulseError(detail || \"LeavePulse request failed\", response.status, payload)",
        "    }",
        "",
        "    return payload as T",
        "  }",
        "",
    ]

    for operation in operations:
        payload = _operation_payload(
            openapi_document=openapi_document,
            contract=contract,
            operation=operation,
        )
        path_key = canonical_path_for_operation(operation, contract=contract)
        path_params = _path_parameters(operation)
        query_parameters = _query_parameters(payload)
        body_schema = _request_body_schema(openapi_document=openapi_document, payload=payload)
        signature_parts: list[str] = []

        for param_name in path_params:
            variable = _to_camel_case(param_name)
            schema_type = "number | string"
            signature_parts.append(f"{variable}: {schema_type}")

        if query_parameters:
            signature_parts.append(
                f'query?: QueryFor<{json.dumps(path_key)}, {json.dumps(operation.method)}>'
            )
        if body_schema:
            signature_parts.append(
                f'body: BodyFor<{json.dumps(path_key)}, {json.dumps(operation.method)}>'
            )

        signature = ", ".join(signature_parts)
        lines.append(f"  {operation.sdk_name}({signature}) {{")
        path_expression = _emit_ts_path_expression(path_key)
        request_args = [
            f'ResponseFor<{json.dumps(path_key)}, {json.dumps(operation.method)}>',
            json.dumps(operation.method),
            path_expression,
        ]
        if query_parameters:
            request_args.append("query as Record<string, unknown> | undefined")
        elif body_schema:
            request_args.append("undefined")
        if body_schema:
            request_args.append("body")
        lines.append(
            "    return this.request<"
            + request_args[0]
            + ">("
            + ", ".join(request_args[1:])
            + ")"
        )
        lines.append("  }")
        lines.append("")

    lines.append("}")
    return "\n".join(lines).rstrip() + "\n"


def generate_python_client_source(
    *,
    contract: PublicApiContract,
    openapi_document: dict[str, Any],
) -> str:
    operations = [operation for operation in contract.operations if operation.include_in_sdk]
    lines = [
        '"""Generated Python client for the LeavePulse Developer API."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "from urllib.parse import quote, urlsplit, urlunsplit",
        "",
        "import httpx",
        "",
        "",
        "class LeavePulseError(RuntimeError):",
        '    """Raised when the LeavePulse API returns a non-success response."""',
        "",
        "    def __init__(self, message: str, status_code: int, payload: Any) -> None:",
        "        super().__init__(message)",
        "        self.status_code = status_code",
        "        self.payload = payload",
        "",
        "",
        "def _build_headers(token: str | None) -> dict[str, str]:",
        "    headers: dict[str, str] = {}",
        "    if token:",
        '        headers["Authorization"] = f"Bearer {token}"',
        "    return headers",
        "",
        "",
        "def _raise_for_payload(response: httpx.Response, payload: Any) -> None:",
        "    if not response.is_error:",
        "        return",
        "",
        "    detail = None",
        "    if isinstance(payload, dict):",
        '        detail = payload.get("detail") or payload.get("title")',
        "    raise LeavePulseError(",
        '        str(detail or response.text or "LeavePulse request failed").strip(),',
        "        response.status_code,",
        "        payload,",
        "    )",
        "",
        "",
        "def _encode_ref(value: str) -> str:",
        '    return quote(value, safe="")',
        "",
        "",
        "def _normalize_base_url(base_url: str) -> str:",
        "    parsed = urlsplit(base_url)",
        '    path = parsed.path.rstrip("/")',
        "    if not path:",
        '        path = "/v1"',
        "    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))",
        "",
        "",
        "class LeavePulseClient:",
        '    """Generated sync client for `https://api.leavepulse.com/v1`."""',
        "",
        "    def __init__(",
        "        self,",
        "        *,",
        "        token: str | None = None,",
        '        base_url: str = "https://api.leavepulse.com/v1",',
        "        timeout: float = 10.0,",
        "        client: httpx.Client | None = None,",
        "    ) -> None:",
        "        self._base_url = _normalize_base_url(base_url)",
        "        self._token = token",
        "        self._owns_client = client is None",
        "        self._client = client or httpx.Client(timeout=timeout)",
        "",
        "    def close(self) -> None:",
        "        if self._owns_client:",
        "            self._client.close()",
        "",
        "    def __enter__(self) -> LeavePulseClient:",
        "        return self",
        "",
        "    def __exit__(self, *_args: object) -> None:",
        "        self.close()",
        "",
        "    def _request(",
        "        self,",
        "        method: str,",
        "        path: str,",
        "        *,",
        "        params: dict[str, Any] | None = None,",
        "        json_body: dict[str, Any] | None = None,",
        "    ) -> Any:",
        "        response = self._client.request(",
        "            method,",
        '            f"{self._base_url}{path}",',
        "            params=params,",
        "            json=json_body,",
        "            headers=_build_headers(self._token),",
        "        )",
        "        payload = response.json() if response.content else None",
        "        _raise_for_payload(response, payload)",
        "        return payload",
        "",
    ]

    lines.extend(
        _generate_python_methods(
            class_indent="    ",
            request_prefix="return self._request",
            operations=operations,
            contract=contract,
            openapi_document=openapi_document,
            async_mode=False,
        )
    )

    lines.extend(
        [
            "",
            "",
            "class AsyncLeavePulseClient:",
            '    """Generated async client for `https://api.leavepulse.com/v1`."""',
            "",
            "    def __init__(",
            "        self,",
            "        *,",
            "        token: str | None = None,",
            '        base_url: str = "https://api.leavepulse.com/v1",',
            "        timeout: float = 10.0,",
            "        client: httpx.AsyncClient | None = None,",
            "    ) -> None:",
            "        self._base_url = _normalize_base_url(base_url)",
            "        self._token = token",
            "        self._owns_client = client is None",
            "        self._client = client or httpx.AsyncClient(timeout=timeout)",
            "",
            "    async def aclose(self) -> None:",
            "        if self._owns_client:",
            "            await self._client.aclose()",
            "",
            "    async def __aenter__(self) -> AsyncLeavePulseClient:",
            "        return self",
            "",
            "    async def __aexit__(self, *_args: object) -> None:",
            "        await self.aclose()",
            "",
            "    async def _request(",
            "        self,",
            "        method: str,",
            "        path: str,",
            "        *,",
            "        params: dict[str, Any] | None = None,",
            "        json_body: dict[str, Any] | None = None,",
            "    ) -> Any:",
            "        response = await self._client.request(",
            "            method,",
            '            f"{self._base_url}{path}",',
            "            params=params,",
            "            json=json_body,",
            "            headers=_build_headers(self._token),",
            "        )",
            "        payload = response.json() if response.content else None",
            "        _raise_for_payload(response, payload)",
            "        return payload",
            "",
        ]
    )

    lines.extend(
        _generate_python_methods(
            class_indent="    ",
            request_prefix="return await self._request",
            operations=operations,
            contract=contract,
            openapi_document=openapi_document,
            async_mode=True,
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def _generate_python_methods(
    *,
    class_indent: str,
    request_prefix: str,
    operations: Iterable[ContractOperation],
    contract: PublicApiContract,
    openapi_document: dict[str, Any],
    async_mode: bool,
) -> list[str]:
    lines: list[str] = []
    async_prefix = "async " if async_mode else ""
    for operation in operations:
        payload = _operation_payload(
            openapi_document=openapi_document,
            contract=contract,
            operation=operation,
        )
        path_types = _path_parameter_types(payload)
        query_parameters = _query_parameters(payload)
        body_fields = _body_fields(openapi_document=openapi_document, payload=payload)
        path_params = _path_parameters(operation)
        canonical_path = canonical_path_for_operation(operation, contract=contract)
        method_parts = ["self"]
        for param in path_params:
            python_name = _to_camel_case(param)
            annotation = "int | str" if path_types.get(param) == "int" else "str"
            method_parts.append(f"{python_name}: {annotation}")
        if body_fields:
            method_parts.append("*")
            for field_name, field_schema, required in body_fields:
                python_name = field_name
                annotation = _schema_type_to_python(field_schema, required=required)
                if required:
                    method_parts.append(f"{python_name}: {annotation}")
                else:
                    method_parts.append(f"{python_name}: {annotation} = None")
        elif query_parameters:
            method_parts.append("**params: Any")
        signature = ", ".join(method_parts)
        lines.append(f"{class_indent}{async_prefix}def {operation.sdk_name.lower() if False else _camel_to_snake(operation.sdk_name or '')}({signature}) -> dict[str, Any]:")

        path_expression = _render_python_path_expression(canonical_path)
        if body_fields:
            lines.append(f"{class_indent}    json_body: dict[str, Any] = {{")
            for field_name, field_schema, required in body_fields:
                if field_schema.get("type") == "array" and not required:
                    lines.append(
                        f'{class_indent}        "{field_name}": {field_name} or [],'
                    )
                else:
                    lines.append(
                        f'{class_indent}        "{field_name}": {field_name},'
                    )
            lines.append(f"{class_indent}    }}")
            lines.append(
                f'{class_indent}    {request_prefix}("{operation.method.upper()}", f"{path_expression}", json_body=json_body)'
            )
        elif query_parameters:
            lines.append(
                f'{class_indent}    {request_prefix}("{operation.method.upper()}", f"{path_expression}", params=params)'
            )
        else:
            lines.append(
                f'{class_indent}    {request_prefix}("{operation.method.upper()}", f"{path_expression}")'
            )
        lines.append("")
    return lines


def _camel_to_snake(value: str) -> str:
    result = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def generate_java_client_source(
    *,
    contract: PublicApiContract,
    openapi_document: dict[str, Any],
) -> str:
    operations = [operation for operation in contract.operations if operation.include_in_sdk]
    lines = [
        "package dev.leavepulse.sdk;",
        "",
        "import com.fasterxml.jackson.databind.JsonNode;",
        "import com.fasterxml.jackson.databind.ObjectMapper;",
        "import java.io.IOException;",
        "import java.net.URI;",
        "import java.net.URLEncoder;",
        "import java.net.http.HttpClient;",
        "import java.net.http.HttpRequest;",
        "import java.net.http.HttpResponse;",
        "import java.nio.charset.StandardCharsets;",
        "import java.util.LinkedHashMap;",
        "import java.util.List;",
        "import java.util.Map;",
        "import java.util.StringJoiner;",
        "",
        "public final class LeavePulseClient {",
        "    private static final ObjectMapper MAPPER = new ObjectMapper();",
        "",
        "    private final HttpClient httpClient;",
        "    private final String baseUrl;",
        "    private final String token;",
        "",
        "    public LeavePulseClient(String token) {",
        "        this(builder().token(token));",
        "    }",
        "",
        "    public LeavePulseClient(HttpClient httpClient, String baseUrl, String token) {",
        "        this.httpClient = httpClient;",
        "        this.baseUrl = normalizeBaseUrl(baseUrl);",
        "        this.token = token;",
        "    }",
        "",
        "    private LeavePulseClient(Builder builder) {",
        "        this(",
        "            builder.httpClient != null ? builder.httpClient : HttpClient.newHttpClient(),",
        "            builder.baseUrl,",
        "            builder.token",
        "        );",
        "    }",
        "",
        "    public static Builder builder() {",
        "        return new Builder();",
        "    }",
        "",
    ]

    for operation in operations:
        payload = _operation_payload(
            openapi_document=openapi_document,
            contract=contract,
            operation=operation,
        )
        path_params = _path_parameters(operation)
        path_types = _path_parameter_types(payload)
        query_parameters = _query_parameters(payload)
        body_fields = _body_fields(openapi_document=openapi_document, payload=payload)
        canonical_path = canonical_path_for_operation(operation, contract=contract)
        signature_parts: list[str] = []
        for param in path_params:
            variable = _to_camel_case(param)
            java_type = "String" if path_types.get(param) != "int" else "String"
            signature_parts.append(f"{java_type} {variable}")
        if body_fields:
            for field_name, field_schema, required in body_fields:
                java_type = _schema_type_to_java(field_schema, required=required)
                signature_parts.append(f"{java_type} {_to_camel_case(field_name)}")
        elif query_parameters:
            signature_parts.append("Map<String, ?> query")
        signature = ", ".join(signature_parts)
        lines.append(f"    public JsonNode {operation.sdk_name}({signature}) {{")
        if body_fields:
            lines.append("        Map<String, Object> payload = new LinkedHashMap<>();")
            for field_name, field_schema, required in body_fields:
                variable = _to_camel_case(field_name)
                if field_schema.get("type") == "array" and not required:
                    lines.append(
                        f'        payload.put("{field_name}", {variable} != null ? {variable} : List.of());'
                    )
                elif required:
                    lines.append(f'        payload.put("{field_name}", {variable});')
                else:
                    lines.append(f"        if ({variable} != null) {{")
                    lines.append(f'            payload.put("{field_name}", {variable});')
                    lines.append("        }")
            rendered_path = _render_java_path_expression(canonical_path)
            lines.append(
                f'        return request("{operation.method.upper()}", {rendered_path}, null, payload);'
            )
        elif query_parameters:
            rendered_path = _render_java_path_expression(canonical_path)
            lines.append(
                f'        return request("{operation.method.upper()}", {rendered_path}, query, null);'
            )
        else:
            rendered_path = _render_java_path_expression(canonical_path)
            lines.append(
                f'        return request("{operation.method.upper()}", {rendered_path}, null, null);'
            )
        lines.append("    }")
        lines.append("")

    lines.extend(
        [
            "    private JsonNode request(",
            "        String method,",
            "        String path,",
            "        Map<String, ?> query,",
            "        Object body",
            "    ) {",
            "        try {",
            "            HttpRequest.Builder builder = HttpRequest.newBuilder(buildUri(path, query))",
            '                .header("Accept", "application/json");',
            "            if (token != null && !token.isBlank()) {",
            '                builder.header("Authorization", "Bearer " + token);',
            "            }",
            "",
            "            if (body != null) {",
            '                builder.header("Content-Type", "application/json");',
            "                builder.method(method, HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(body)));",
            "            } else {",
            "                builder.method(method, HttpRequest.BodyPublishers.noBody());",
            "            }",
            "",
            "            HttpResponse<String> response = httpClient.send(",
            "                builder.build(),",
            "                HttpResponse.BodyHandlers.ofString()",
            "            );",
            '            String payload = response.body() == null ? "" : response.body();',
            "            if (response.statusCode() >= 400) {",
            "                throw new LeavePulseError(",
            '                    payload.isBlank() ? "LeavePulse request failed" : payload,',
            "                    response.statusCode(),",
            "                    payload",
            "                );",
            "            }",
            "            return payload.isBlank() ? MAPPER.nullNode() : MAPPER.readTree(payload);",
            "        } catch (InterruptedException ex) {",
            "            Thread.currentThread().interrupt();",
            '            throw new RuntimeException("LeavePulse request failed", ex);',
            "        } catch (IOException ex) {",
            '            throw new RuntimeException("LeavePulse request failed", ex);',
            "        }",
            "    }",
            "",
            "    private URI buildUri(String path, Map<String, ?> query) {",
            '        StringBuilder value = new StringBuilder(baseUrl).append(path);',
            "        if (query != null && !query.isEmpty()) {",
            '            StringJoiner joiner = new StringJoiner("&");',
            "            for (Map.Entry<String, ?> entry : query.entrySet()) {",
            "                Object raw = entry.getValue();",
            "                if (raw == null) {",
            "                    continue;",
            "                }",
            "                joiner.add(encode(entry.getKey()) + \"=\" + encode(String.valueOf(raw)));",
            "            }",
            "            String queryString = joiner.toString();",
            "            if (!queryString.isBlank()) {",
            '                value.append("?").append(queryString);',
            "            }",
            "        }",
            "        return URI.create(value.toString());",
            "    }",
            "",
            "    private static String normalizeBaseUrl(String baseUrl) {",
            "        URI uri = URI.create(baseUrl);",
            '        String path = uri.getPath() == null ? "" : uri.getPath().replaceAll("/+$", "");',
            '        if (path.isBlank() || "/".equals(path)) {',
            '            path = "/v1";',
            "        }",
            "        return URI.create(",
            '            uri.getScheme() + "://" + uri.getAuthority() + path',
            "        ).toString();",
            "    }",
            "",
            "    private static String encode(String value) {",
            "        return URLEncoder.encode(value, StandardCharsets.UTF_8);",
            "    }",
            "",
            "    public static final class Builder {",
            "        private HttpClient httpClient;",
            '        private String baseUrl = "https://api.leavepulse.com/v1";',
            "        private String token;",
            "",
            "        public Builder httpClient(HttpClient httpClient) {",
            "            this.httpClient = httpClient;",
            "            return this;",
            "        }",
            "",
            "        public Builder baseUrl(String baseUrl) {",
            "            this.baseUrl = baseUrl;",
            "            return this;",
            "        }",
            "",
            "        public Builder token(String token) {",
            "            this.token = token;",
            "            return this;",
            "        }",
            "",
            "        public LeavePulseClient build() {",
            "            return new LeavePulseClient(this);",
            "        }",
            "    }",
            "}",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"
