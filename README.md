# leavepulse-public-api-contract

Code-first public API contract package for LeavePulse.

This package is the single source of truth for the developer-facing API:
- public operation registry
- canonical OpenAPI document
- developer docs manifest and HTML shell
- generated SDK clients for TypeScript, Python, and Java

Main entrypoints:
- `src/leavepulse_public_api_contract/public_api.py`: public route registry
- `src/leavepulse_public_api_contract/openapi.py`: OpenAPI generator
- `src/leavepulse_public_api_contract/docs.py`: docs manifest and docs HTML
- `src/leavepulse_public_api_contract/sdk_generation.py`: SDK generators

When adding a new public endpoint:
1. register it in `public_api.py`
2. make sure the runtime route exists in `server-service`
3. run `python /mnt/Programing/Projects/LeavePulse/sdk/scripts/generate_public_api_assets.py`
4. run the package and SDK tests

Canonical public base URL:

```text
https://api.leavepulse.com/v1
```
