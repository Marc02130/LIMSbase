# Requirements — critical security

Depends on the library requirements. Checks assume an authenticated user unless the requirement says otherwise. Organization membership is the caller's `org_ids` set from `OrganizationAccessControl`, the same set summary queries use.

| ID | Requirement |
|---|---|
| SEC-1 | `GET` or `POST` `/<facility>/core/search` and `/<facility>/core/search_results` without a session redirect to login or return 401. They do not run a search. |
| SEC-2 | A signed-in search still uses `get_search_results`, which limits rows to `organization_id IN org_ids` (or `id IN org_ids` for `Organization`). Field names interpolated into the modal HTML are escaped. |
| SEC-3 | `POST /<facility>/core/get_row/<table>/ajax` returns a row only when that row's `organization_id` is in the caller's `org_ids`. A row in another organization returns an empty result, not the row. |
| SEC-4 | `get_row` rejects a table the caller's role cannot read, and rejects a requested field that is not a column of that table. The response does not include other attributes. |
| SEC-5 | `POST /<facility>/billing/get_price/ajax` follows SEC-3 and SEC-4 for the price row it returns. |
| SEC-6 | `GET /<facility>/core/files/<table>/<row>/<filename>` and `GET /<facility>/core/file/<table>/<filename>` return the file only when the row is in the caller's `org_ids`. Otherwise the response is 404. `../` in the filename does not escape the directory. |
| SEC-7 | `POST /<facility>/core/change_user` succeeds only when the caller's current role level name is `admin` (case-insensitive). Any other caller gets a failure and their org scope does not change. |
| SEC-8 | A successful `change_user` writes an audit log line containing actor id, target user id, facility name, and a timestamp. The line does not contain a password or a session cookie. |
| SEC-9 | `POST` of `update_table_rows`, `change_role`, `change_user`, `modal_add_submit`, and `generate_invoices` without a CSRF token returns 400 and does not write. The same request with a valid token reaches the existing handler. |
| SEC-10 | `multiple_entry` does not delete a `csrf_token` error. A missing or wrong token does not save. |
| SEC-11 | A stored field value containing `<script>` is not returned as live HTML from a summary link, a file link, or the save-confirmation message. The text is escaped. |
| SEC-12 | `GET` or `POST /<facility>/core/cache/` is forbidden for a caller whose level is not `admin`. Setting a cache key or a version is rejected for every caller. |
| SEC-13 | An `action` row whose `namespace` is outside `iggybase`, or whose function is not on the code allowlist, does not import that module and does not call that function. The action status is failure. `utilities.get_func` uses the same rule. |
| SEC-14 | One function that already lives under `iggybase` and is on the allowlist still resolves and can be called. |

Analysis §7, §8.11 (script SQL), and §8.13 (log noise) are not requirements of this plan.
