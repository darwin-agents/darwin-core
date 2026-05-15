# Changelog

All notable changes to Darwin Core will be documented in this file.

## [Unreleased]

### Added
- **Unified Configuration:** Standardized all environment variables to a clean `DARWIN_WEB_` prefix, completely cleaning up the `.env.example` configurations.
- **Hierarchical Test Suite:** Organized over 120 tests into a mirrored sub-package hierarchy (`core`, `browser`, `execution`, `intelligence`, `integrations`, `playbook`, `security`) corresponding to the main `darwin_core` source tree.

### Changed
- **Resilient Architecture Promotion:** Officially promoted the state-of-the-art, resilient `darwin_web2` architecture into `darwin_core/agents/web`. It is now the primary, default orchestration engine.
- **Sub-package Modularization:** Reorganized the previously flat v2 architecture into cleanly separated architectural layers: `core`, `browser`, `execution`, `intelligence`, `integrations`, `playbook`, and `security`.
- **Import Rewrite:** Refactored over 100 internal imports across the codebase to reflect the new nested sub-package syntax.
- **Test Modernization:** Moved browser-agent tests under `tests/agents/web/` with names aligned to each sub-package (`browser`, `core`, `execution`, and so on).

### Removed
- **Legacy v1 Architecture:** Completely deleted the old heuristic-based `darwin_web` v1 orchestration code.
- **Obsolete Wrappers:** Removed legacy wrapper scripts (`openrouter_web_agent.py`, `web_recipe_store.py`) and their corresponding tests that depended on the deprecated v1 `action_runtime`.
- **Stale Dependencies:** Inlined critical browser connection payloads to fully decouple `darwin_web2` from any legacy `darwin_core` dependencies before the merger.
