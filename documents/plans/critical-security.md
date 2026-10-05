# Plan — critical security

Spec: `documents/spec/critical-security.md`
Requirements: `documents/requirements/critical-security.md`

Depends on the library plan. The application imports on Python 3.14 before this plan starts.

Each slice gets a MySQL-backed test for the requirement IDs it names. Do not mock the organization filter. Do not start the next slice until the current one has been reviewed.

## Slice 1 — Search

SEC-1, SEC-2.

`@login_required` on `search` and `search_results`. Escape field names in the modal HTML. Leave `get_search_results` org logic in place.

Test: anonymous request does not return search rows. A signed-in user does not receive a row outside `org_ids`.

## Slice 2 — `get_row` and `get_price`

SEC-3, SEC-4, SEC-5.

Org-scoped read using `org_ids`, role check on the table, column allowlist. Same column and org rules on `get_price`.

Test: another organization's row is absent. An unknown field name is absent. A table the role cannot read is 404.

## Slice 3 — Files

SEC-6.

Resolve the owning row through the org-scoped read before `send_from_directory`. 404 otherwise.

Test: in-org file is returned. Out-of-org path is 404. A `../` filename does not leave the directory.

## Slice 4 — `change_user`

SEC-7, SEC-8.

`caller_is_admin()` gate, then the existing same-facility lookup. Audit log line on success.

Test: a non-admin post leaves org scope unchanged. An admin post writes the audit line and does not log a password.

## Slice 5 — CSRF

SEC-9, SEC-10.

`CSRFProtect`, meta tag, `X-CSRFToken` from `main.js`, `action_summary.js`, `billing_summary.js`, and the modal submit caller. Remove the `csrf_token` error deletion in `multiple_entry`.

Test: each listed POST without a token returns 400 and does not write. `multiple_entry` with a bad token does not save.

## Slice 6 — Stored HTML

SEC-11.

Move summary anchors out of the SQL expression. Escape link text and URLs in Python, including file links and `saved_data`.

Test: a field value `<script>` is escaped in the summary payload and in the save message.

## Slice 7 — Cache

SEC-12.

Admin-only read. Delete the set-key and set-version behavior.

Test: a non-admin receives 403. An admin post of set-key does not change the cache.

## Slice 8 — Action imports

SEC-13, SEC-14.

Allowlist module. Gate `execute_action`, `get_func`, and the workflow `import_module` of `routes`.

Test: namespace `os` does not import. One allowlisted `iggybase` function still resolves.

## Out of scope

Analysis §7, §8.11, §8.13, and any new impersonation UI.
