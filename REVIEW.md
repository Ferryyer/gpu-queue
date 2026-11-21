# Inspire Queue review rules

Read the rules from the base commit. For each finding, cite the changed path and line, the input or state that triggers it, and the behavior callers can observe.

- Keep submission and approval separate. Match approval to the exact task snapshot, digest and selected resources before dispatch. Missing or stale approval must leave the task unstarted.
- Reconcile ambiguous start, submit, stop and release results before retrying. Preserve the queue's one-logical-execution contract across crashes, duplicate clicks and late results.
- Keep resource ownership, reuse and release distinct. Check resource identity and service ownership before changing a resource, and preserve active and approved work during teardown.
- Preserve inputs, resource requirements and result identity across the CLI, task page, service and launcher. Keep failed, uncertain, cancelled and completed states distinguishable in the UI.
- Inspect the existing tests for each changed path. Use mocked or isolated fixtures for platform operations. Treat missing GPU, desktop or platform evidence as a verification gap when that evidence matters.
- Verify provenance and checksums when download or update behavior changes. Keep credentials, local paths, user records and runtime data out of public commits, logs and artifacts.
