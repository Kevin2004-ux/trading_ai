# Trading AI Documentation

Trading AI is a deterministic paper-trading research system. It does not place real brokerage orders.

Start here:

- `../README.md`: Project overview, setup, and common commands.
- `RUNBOOK.md`: Local operations, diagnostics, paper workflows, reports, jobs, and troubleshooting.
- `SAFETY.md`: Safety boundaries and deterministic guardrails.
- `ARCHITECTURE.md`: Pipeline and module map.
- `BUILD_ROADMAP.md`: Implementation roadmap for dynamic discovery, best-available outputs, planner upgrades, and capability tracking.
- `CLI_REFERENCE.md`: Command reference.

Core principle: SQLite and deterministic constraints are the source of truth. Gemini, Pinecone memory, reports, and alerts can explain or summarize, but they cannot override hard gates.
