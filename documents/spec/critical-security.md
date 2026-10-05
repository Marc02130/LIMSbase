# Spec — critical security

Meets `documents/requirements/critical-security.md`. One slice per group below. Shared helper for the admin check lives in one place and is used by `change_user` and the cache route.

## Admin level

`Level` is a table, not an enum. The caller's current role is `User.current_user_role_id` → `UserRole` → `Role.role_level`. The level name is `Level.name`.

`caller_is_admin()` is true when that name strips and lowercases to `admin`. No other level passes. If a facility's data uses a different word, this check stays closed until the requirement is changed. Do not treat "shares a facility role" as admin.

## Search (SEC-1, SEC-2)

`iggybase/core/routes.py` functions `search` and `search_results` have no `@login_required`. `before_request` builds `g.oac` only for an authenticated user. `g_helper.get_org_access_control()` will still construct one. For an anonymous user, `get_default_org_ids()` returns only the organization named `Everyone`, and `get_search_results` then returns those rows.

Add `@login_required` to both routes. Do not weaken `get_search_results`. It already applies `organization_id IN org_ids`, and `id IN org_ids` when the table is `Organization`.

`ModalForm.search_results` concatenates field names into an HTML table. Escape those names with `markupsafe.escape` in the same slice. That is SEC-2, not a new finding.

## Row fetch (SEC-3, SEC-4, SEC-5)

`get_row` in `organization_access_control.py` defaults `org_filter` to false. The true branch compares `organization_id` to `current_org_id` only, which is narrower than summary queries and wrong for a user with several orgs.

The ajax route in `core/routes.py` calls `oac.get_row(table_name, criteria)` and then `getattr(row, field)` for every client-supplied field name.

For this route:

1. Resolve the table with the existing role check (`RoleAccessControl.has_access` or the same function summaries use). If the role cannot read it, return 404.
2. Load the row with `organization_id.in_(oac.org_ids)`. Do not use the `current_org_id` equality branch. Leave the default of `get_row` unchanged for other callers.
3. Return a field only when it is a column key on `row.__table__.columns`. Ignore anything else.

`billing/routes.py` `get_price` returns client-named attributes off the price row. Apply the same column check and the same org rule to that row.

## Files (SEC-6)

`file_row` and `file` call `send_from_directory` after a login check. `send_from_directory` already blocks path escape. Keep it.

Before sending, load the row by table name and row name through the org-scoped read used above. `file_row` uses the `<row_name>` path segment. `file` uses the table directory only; still require a row in that table whose name matches the filename's row key the storage layout uses (`UPLOAD_FOLDER / table / row_name / filename` versus `FILE_FOLDER / table / filename`). If no in-org row owns that path, return 404. Do not reveal whether an out-of-org row exists.

## User switch (SEC-7, SEC-8)

`RoleAccessControl.change_user` returns a user who shares any role id in the caller's facility. The route then calls `oac.set_user`, which rebuilds org scope. There is no audit.

In the route, before `set_user`:

1. Call `caller_is_admin()`. If false, return `{"success": false}` and do not touch the session.
2. If true, keep the existing shared-role lookup so an admin cannot switch to a user outside the facility.
3. On success, log with logger name `iggybase.audit` at info: actor user id, target user id, facility name, UTC timestamp. Do not log the request body beyond the target id.

Do not add a banner, a time limit, or a new impersonation session. `main.js` may keep posting to the route.

## CSRF (SEC-9, SEC-10)

Enable `flask_wtf.csrf.CSRFProtect` on the app in `create_app`.

These handlers read JSON or save with no token check:

| Route | Caller |
|---|---|
| `core.update_table_rows` | `static/action_summary.js` |
| `core.change_role` | find the click handler in the same slice and send the token |
| `core.change_user` | `static/main.js` |
| `core.modal_add_submit` | the script that posts the modal |
| `billing` `generate_invoices` | `static/billing_summary.js` |

Put the token in a `<meta name="csrf-token">` in `templates/base.html`, using the Flask-WTF generator. JavaScript sends it as `X-CSRFToken`. Flask-WTF accepts that header by default.

A missing or invalid token is a 400 and the handler body does not run.

`multiple_entry` calls `validate_csrf_data` and then `del fg.form_class.errors['csrf_token']` after rebuilding the form. Delete that `del`. Validate the submitted token before the form is rebuilt. A token failure skips `FormParser.save`.

`/healthz` and the static and login views are not given a second token requirement beyond what Flask-Security-Too already applies to its own forms.

## Stored HTML (SEC-11)

Three builders insert raw values into anchors:

- `organization_access_control.py` builds `'<a href="' + link + col + '">' + col + '</a>'` as a SQL expression inside the summary query.
- `table_query.py` wraps file names the same way in Python.
- `core/routes.py` `saved_data` appends an anchor into the flash-style message. The error branch already strips `<` and `>`. The success branch does not escape `row_info['name']`.

Stop building the summary anchor in SQL. Select the raw column. When the result is formatted in Python, escape the visible text and the URL with `markupsafe.escape` before wrapping them in `<a>`. Escape file names and `saved_data` names the same way. Do not mark the unescaped column as safe in the template.

A value of `<script>` in a linked field must appear in the response as escaped text, not as an element.

## Cache (SEC-12)

`/core/cache/` is login-only and can set arbitrary keys, including summary JSON.

At the start of `cache`, if `caller_is_admin()` is false, abort 403.

Remove the `set_key` and `set_version` branches. Posting those buttons does not call `cache.set` or `cache.set_version`. Reading a key may remain for an admin.

## Action imports (SEC-13, SEC-14)

`Action.execute_action` does `import_module(namespace)` and `getattr(module, function)` for whatever the `action` row stores. `utilities.get_func` does the same.

Add `iggybase/core/action_allowlist.py`: a dict of module name to a set of function names. Both call sites consult it.

Rules:

1. The module name starts with `iggybase.`.
2. The module is a key in the dict and the function name is in its set.
3. Only then import and call.
4. Otherwise log the rejection and return a failed status (`status` false). Do not import.

Build the dict from functions that exist in the tree under `iggybase.core`, `iggybase.billing`, `iggybase.murray`, `iggybase.smallmolecule`, and `iggybase.sequencing` and that are referenced as actions. Record the inventory in the allowlist module. A name that exists only in a database row is not added by guessing. SEC-14 is satisfied by one in-tree function on that list.

`core/routes.py` also imports `iggybase.<module>.routes` from a workflow step's module name. That is a separate path. Limit it to the blueprint module names already in the tree (`core`, `billing`, `murray`, `smallmolecule`, `sequencing`, `laboratory`, `admin`, `interfaces`). Do not `import_module` an arbitrary string there either.
