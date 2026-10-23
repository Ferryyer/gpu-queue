CREATE TABLE gpuq_tasks (
 id TEXT PRIMARY KEY NOT NULL,
 digest TEXT NOT NULL,
 payload TEXT NOT NULL,
 approved_at TEXT,
 claimed_at TEXT,
 position INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE TABLE gpuq_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
--> statement-breakpoint
INSERT INTO gpuq_meta (key,value) VALUES ('revision','0');
--> statement-breakpoint
CREATE TABLE gpuq_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, action TEXT NOT NULL, at TEXT NOT NULL);
