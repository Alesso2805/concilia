# ADR-0004: Uploaded files and exports stored in PostgreSQL

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

Analysts upload bank statements and receivable lists (CSV or XLSX, up to 5 MB), and the worker produces Excel exports of a period. Files are few and small. Each upload is parsed once into a preview and then confirmed or discarded, and exports are downloaded within a day. Demo organizations, with all their files, are deleted after a few hours.

## Decision

Store file contents in PostgreSQL as `bytea`:

- `import_files.content` holds the uploaded file, together with `sha256`, `size_bytes`, the original `filename` and a copy of the import profile (`profile_snapshot`).
- `exports.content` holds the generated workbook, with `expires_at` 24 hours after creation.

Size limits are enforced at three points: Caddy rejects requests over 6 MB, the API rejects files over 5 MB before reading them fully, and the parser stops at 10 000 rows. File type is decided by content, never by extension or `Content-Type` (CN-09).

Lifecycle:

- Uploaded files stay with their `import_files` row, because a confirmed or voided import must remain inspectable. Their parsed rows (`import_rows`) are deleted on confirm or discard.
- `app_cleanup` deletes expired exports and discards previews abandoned for more than 24 hours.
- `app_reset_demo` deletes an expired demo organization's files together with the rest of its data.

Code reads and writes contents only through the `imports` and `reporting` application layers, never by querying the column from another module.

**Path to object storage.** If files grew in number or size, they would move to S3-compatible storage as follows:

1. Add a `FileStore` port in the `application` layer of `imports` and `reporting`, with a PostgreSQL adapter that keeps today's behavior.
2. Add a nullable `storage_key` column, write new files to the object store, and let the adapter read whichever of `content` or `storage_key` is set.
3. Backfill old rows, make `content` nullable, and have `app_cleanup` and `app_reset_demo` enqueue deletion of objects instead of relying on row deletion.

## Consequences

- One backup (`pg_dump`) covers data and files, and a file can never refer to a row that does not exist.
- RLS protects files exactly like any other organization data.
- Deleting a demo or an expired export is a row deletion, with no orphaned objects to chase.
- The database and its backups grow with every upload. At the expected volume (a few uploads per month per real organization, and demos deleted after 4 hours) this is negligible.
- A 5 MB file is held in memory while the worker parses it, which is acceptable for one worker on a small server.

## Alternatives considered

- **Local filesystem volume.** Rejected: a second thing to back up, no RLS, and orphaned files when rows are deleted.
- **S3 or MinIO from the start.** Rejected for the MVP: an extra service or monthly cost, and deletion becomes a two-system operation.
