from __future__ import annotations

import json

import msgspec

from .models import DocsManifest, DocsOperation, DocsSection, PublicApiContract
from .openapi import canonical_path_for_operation
from .public_api import GROUP_METADATA


def build_docs_manifest(
    *,
    contract: PublicApiContract,
    openapi_url: str = "/v1/openapi.json",
) -> DocsManifest:
    sections: list[DocsSection] = []
    for group_id, (title, description) in GROUP_METADATA.items():
        operations = tuple(
            DocsOperation(
                id=operation.id,
                method=operation.method.upper(),
                path=canonical_path_for_operation(operation, contract=contract),
                summary=operation.summary,
                description=operation.description,
                auth_kind=operation.auth_kind,
            )
            for operation in contract.operations
            if operation.docs_group == group_id
        )
        if not operations:
            continue
        sections.append(
            DocsSection(
                id=group_id,
                title=title,
                description=description,
                operations=operations,
            )
        )

    return DocsManifest(
        title=contract.title,
        description=contract.description,
        canonical_base_url=contract.canonical_base_url,
        openapi_url=openapi_url,
        auth_scheme="Bearer token for authenticated endpoints; unauthenticated access for public catalog routes.",
        sdk_languages=("TypeScript", "Python", "Java"),
        sections=tuple(sections),
    )


def render_docs_html(manifest: DocsManifest) -> str:
    manifest_json = json.dumps(msgspec.to_builtins(manifest), ensure_ascii=True)
    section_cards = "\n".join(
        f"""
        <section class="section-card" id="group-{section.id}">
          <div class="section-head">
            <h3>{section.title}</h3>
            <p>{section.description}</p>
          </div>
          <ul class="operation-list">
            {''.join(
                f'<li><code>{operation.method}</code><span>{operation.path}</span><small>{operation.summary}</small></li>'
                for operation in section.operations
            )}
          </ul>
        </section>
        """
        for section in manifest.sections
    )
    language_badges = "".join(
        f"<span class=\"lang-pill\">{language}</span>" for language in manifest.sdk_languages
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{manifest.title}</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #0a111a;
        --surface: rgba(12, 24, 37, 0.72);
        --surface-strong: #0f1b2c;
        --border: rgba(130, 170, 200, 0.18);
        --text: #ebf3fb;
        --muted: #8ea6bd;
        --brand: #56c7d9;
        --accent: #9fe870;
        --shadow: 0 24px 80px rgba(0, 0, 0, 0.34);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Inter, system-ui, sans-serif;
        background:
          radial-gradient(circle at top left, rgba(86, 199, 217, 0.18), transparent 26%),
          radial-gradient(circle at top right, rgba(159, 232, 112, 0.15), transparent 22%),
          linear-gradient(180deg, #07111a 0%, #0b1320 52%, #081018 100%);
        color: var(--text);
      }}
      .page {{
        padding: 28px;
        display: grid;
        gap: 24px;
      }}
      .hero {{
        display: grid;
        gap: 20px;
        grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr);
      }}
      .hero-main, .hero-side, .section-card {{
        border: 1px solid var(--border);
        background: var(--surface);
        backdrop-filter: blur(18px);
        border-radius: 24px;
        box-shadow: var(--shadow);
      }}
      .hero-main {{
        padding: 28px;
      }}
      .hero-side {{
        padding: 24px;
        display: grid;
        gap: 14px;
        align-content: start;
      }}
      .eyebrow {{
        display: inline-flex;
        gap: 10px;
        align-items: center;
        color: var(--brand);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-size: 12px;
      }}
      h1, h2, h3, p {{
        margin: 0;
      }}
      h1 {{
        font-family: "Fraunces", Georgia, serif;
        font-size: clamp(2.2rem, 4vw, 3.7rem);
        line-height: 1.05;
        max-width: 12ch;
      }}
      .lead {{
        color: var(--muted);
        max-width: 62ch;
        font-size: 1.05rem;
        line-height: 1.6;
      }}
      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-top: 20px;
      }}
      .meta-card {{
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 16px;
        background: rgba(6, 14, 24, 0.55);
      }}
      .meta-card strong {{
        display: block;
        font-size: 12px;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 8px;
      }}
      .meta-card code {{
        font-size: 0.95rem;
        color: var(--accent);
        word-break: break-all;
      }}
      .lang-pill {{
        display: inline-flex;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(9, 18, 29, 0.85);
        color: var(--text);
        margin-right: 8px;
        margin-bottom: 8px;
      }}
      .section-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 18px;
      }}
      .section-card {{
        padding: 22px;
      }}
      .section-head {{
        display: grid;
        gap: 8px;
        margin-bottom: 14px;
      }}
      .section-head p {{
        color: var(--muted);
        line-height: 1.5;
      }}
      .operation-list {{
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 12px;
      }}
      .operation-list li {{
        border-top: 1px solid rgba(130, 170, 200, 0.12);
        padding-top: 12px;
        display: grid;
        gap: 4px;
      }}
      .operation-list li:first-child {{
        border-top: 0;
        padding-top: 0;
      }}
      .operation-list code {{
        color: var(--brand);
        font-weight: 700;
      }}
      .operation-list span {{
        font-size: 0.98rem;
      }}
      .operation-list small {{
        color: var(--muted);
        line-height: 1.45;
      }}
      .reference {{
        border: 1px solid var(--border);
        background: rgba(7, 14, 22, 0.78);
        backdrop-filter: blur(16px);
        border-radius: 28px;
        overflow: hidden;
        min-height: 72vh;
      }}
      @media (max-width: 980px) {{
        .page {{ padding: 18px; }}
        .hero {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="page">
      <section class="hero">
        <div class="hero-main">
          <div class="eyebrow">LeavePulse Developer API</div>
          <h1>Public contract, docs, and SDKs from one source</h1>
          <p class="lead">{manifest.description}</p>
          <div class="meta-grid">
            <div class="meta-card">
              <strong>Base URL</strong>
              <code>{manifest.canonical_base_url}</code>
            </div>
            <div class="meta-card">
              <strong>OpenAPI</strong>
              <code>{manifest.openapi_url}</code>
            </div>
            <div class="meta-card">
              <strong>Auth</strong>
              <span>{manifest.auth_scheme}</span>
            </div>
          </div>
        </div>
        <aside class="hero-side">
          <div>
            <div class="eyebrow">SDKs</div>
            <h2>Generated clients</h2>
          </div>
          <div>{language_badges}</div>
          <p class="lead">The public OpenAPI document and SDK clients are generated from the same contract registry, so docs and code stay aligned.</p>
        </aside>
      </section>
      <section class="section-grid">
        {section_cards}
      </section>
      <section class="reference">
        <script id="api-reference" data-configuration='{{"spec":{{"url":"{manifest.openapi_url}"}},"theme":"default","layout":"modern","hideDownloadButton":false}}'></script>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
      </section>
    </div>
    <script type="application/json" id="leavepulse-docs-manifest">{manifest_json}</script>
  </body>
</html>"""
