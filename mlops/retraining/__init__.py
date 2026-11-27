"""DBX-08: retraining policies (versioned MLOps DTOs, local SQLite), condition evaluation,
proposals, server-side guardrails and an optional local scheduler.

Every launch goes through TrainingService.launch (single launch path, authorization lock).
New models always stay candidates: no alias, approval or deployment is ever automatic."""
