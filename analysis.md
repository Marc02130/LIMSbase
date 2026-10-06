# Iggybase LIMS — Codebase Analysis

**Repository:** LIMSbase (`iggybase`)
**First commit:** 2015-07-09
**Original development era:** ~2015–2017 (Python 3.4 / Flask 0.12)
**Re-reviewed:** 2026-10-06, after the in-place revival on `master`
**Size:** ~13,200 lines of application Python across ~100 modules, plus eight security test modules
**Runtime now:** Python 3.14, Flask 3.1, SQLAlchemy 2.1, gunicorn, MySQL 8, Docker Compose on `127.0.0.1:18000`
**Runtime then:** Flask + SQLAlchemy + MySQL, Apache `mod_wsgi`, Harvard FAS core facilities

This document reviews the architecture, the security findings, and what the 2026 revival changed. Sections that describe the product (tenancy, metadata engine, billing, domain modules) still describe the code. Sections that graded the 2015 stack, the missing tests, or the open authorization holes are updated below. Where a finding is unchanged, it says so.

---

## 1. Executive summary

Iggybase is a **metadata-driven laboratory information management system** built for Harvard FAS core facilities. It is not a tutorial app and not a thin CRUD wrapper. It is a working product that modeled:

- multi-facility tenancy (Bauer / SMMS, Murray oligo, sequencing, general laboratory)
- role × facility × organization-tree access control
- generic CRUD generated from database metadata
- workflows with before/after actions
- core-facility billing and PDF invoicing
- domain-specific science tools (lipid analysis, oligo fulfillment, Illumina import)

The central design decision is correct: **the lab schema is data, not code.** Tables, fields, forms, menus, routes, permissions, and workflows live in MySQL. The Python application is a generic engine plus a few domain plugins.

That design is still how a configurable LIMS should work. The 2015 process around it had end-of-life dependencies, no tests, and authorization holes at the edges. The 2026 revival kept the engine and replaced the runtime, then closed the high findings in §8. It did not fix the production defects in §7, the script SQL in §8.11, or the request-path prints in §8.13. Compose publishes the web app on localhost only.

**The short version:** the metadata model, the access-control idea, the workflow engine, and the billing rules are still the product. The process that interprets them now runs on Python 3.14 under gunicorn. It is fit to run on this machine. It is not a finished security review, and it is not ready to expose beyond localhost.

| Area | Grade | Notes |
|---|---|---|
| Domain model | Strong | Table/field/role/org/workflow is the hard part, and it is here |
| Access-control *idea* | Strong | Facility × role × org tree is the right LIMS tenancy model |
| Access-control *enforcement* | Improved | Search, row fetch, files, `change_user`, cache, action import, and summary HTML are closed in code. Bulk update, modal submit, and §7 defects remain |
| Generic CRUD engine | Strong concept, fragile code | Form generator/parser and table queries are ambitious. SQLAlchemy 2 required local join fixes; the engine was not rewritten |
| Billing | Strong, untested in this pass | Real invoicing, not a script. No invoice test was added |
| Security | Partial | §8.1–§8.10 and §8.12 addressed. §8.11 and §8.13 left open. Bound to `127.0.0.1` |
| Test coverage | Narrow | Eight MySQL-backed unittest modules, one per security slice. No billing, form, or workflow suite |
| Operability | Local Docker | gunicorn, Compose, `/healthz`. The Apache 2.2 vhost is still in the tree and is not the server. Cache is still in-process |
| Revive-in-place | Done for the planned slices | Python 3.14, current pins, security slices, Compose. An empty database still has no facility screens until metadata is loaded |

---

## 2. What this system is

### 2.1 Product

Iggybase is a multi-tenant LIMS for Harvard Faculty of Arts and Sciences core facilities. From code, templates, invoices, and scripts, the deployed facilities include:

| Facility / module | What it does |
|---|---|
| **Bauer / SMMS** (`smallmolecule`) | Small-molecule core. QC summaries, lipid analysis from vendor CSVs, charge methods |
| **Murray** (`murray`) | Oligo ordering: requested → ordered → received → canceled |
| **Sequencing** (`sequencing` + `scripts/sequencing`) | Illumina run import from `RunInfo.xml`, line-item generation |
| **Laboratory** (`laboratory`) | Generic lab module; mostly a blueprint shell |
| **Billing** (`billing`) | Monthly line-item review, invoice generation, WeasyPrint PDFs, Harvard 33-digit codes |
| **Admin** (`admin`) | Users, roles, facilities, organizations, menus, routes, metadata |
| **Core** (`core`) | The product: generic summary / detail / data entry / workflow / search |

The invoice letterhead is hardcoded to FAS Division of Science, Northwest Lab. Charge-method files in `files/charge_method/` are real operational artifacts. The SPINAL interface checks Harvard expense codes against an external accounting database.

This is a **single-campus, multi-core** system. “Multi-facility” means multiple cores at Harvard FAS, not a SaaS LIMS.

### 2.2 Users and tenancy

The tenancy model is three-dimensional:

```
Facility  (bauer, murray, helium, …)
  └─ Role = Facility × Level   (admin, manager, user, …)
       └─ User  (may have many roles; one current_user_role_id)

Organization tree
  Facility.root_organization_id
    └─ PI / group orgs (public, billable, have addresses)
         └─ child orgs
  Special org: "Everyone"
```

A user belongs to one or more organizations via `user_organization` and may hold positions (`manager`, lab admin) via `user_organization_position`. Data rows carry `organization_id`. Access to a row is “your org, your descendant orgs, or Everyone.”

A user may have roles in more than one facility. Switching facilities changes the current role and rebuilds the allowed route map. Switching roles inside a facility is a first-class UI action.

### 2.3 What “LIMS” means here

This is not an instrument-control LIMS and not an ELN. It is a **core-facility operations LIMS**:

- request / order intake
- sample and work-item tracking
- status boards (ordered, received, QC pass/fail)
- configurable data entry for whatever tables a facility invents
- workflows that walk a work-item group through steps
- billing against price lists and charge methods
- file attachments on rows
- PDF invoices

Science-specific computation is limited and local: lipid-class aggregation, oligo status transitions, Illumina metadata import. The engine is generic; the science rides on top as modules and scripts.

---

## 3. Historical and technical context

### 3.1 Stack

Direct pins in `requirements.txt` (2026-10-05), installed on Python 3.14:

```
Flask               3.1.3
Werkzeug            3.1.9
Jinja2              3.1.6
SQLAlchemy          2.1.3      (session.query() kept; no Flask-SQLAlchemy)
PyMySQL             1.2.3
Flask-Login         0.6.3
flask-security-too  5.9.1      (argon2 via libpass and argon2-cffi)
Flask-WTF           1.3.0
WTForms             3.2.2
Pillow              12.3.0
WeasyPrint          70.0
Flask-WeasyPrint    1.2.0
gunicorn            26.2.0
cachelib            0.17.0
```

`mysql-connector-python-rf` and `mod-wsgi` are gone from the requirements. Flask-Bootstrap 3 is not installed; `iggybase/extensions.py` shims the Bootstrap 3 helpers the templates already call. SQLAlchemy 2 kept `query_property`. `sqlalchemy.orm.relation` did not survive and was replaced with `relationship` where import required it. `Query.join()` takes one target, so the facility/role query and `table_query_fields` join one target at a time.

The 2015 freeze this section used to list (Python 3.4.1, Flask 0.12.1, Flask-Security 1.7.5, WeasyPrint 0.36, Pillow 4) is historical. `iggybase.wsgi` and `apache_conf` are still in the tree from that era. `run.py` calls `iggybase.run()` with no `debug=True`. The image runs gunicorn.

`config.py` is in the repository. It reads the environment and raises `config.MissingConfig` when a required variable is missing or blank. `.env` is gitignored. `.env.example` has placeholders and no real secrets. `SQLALCHEMY_DATABASE_URI` is built with `urllib.parse.quote` when it is unset, and `database.py` still appends `DATA_DB_NAME`.

### 3.2 Deployment

The server is Docker Compose, not Apache.

- `Dockerfile`: `python:3.14`, user `iggybase` (uid 1000), gunicorn `--bind 0.0.0.0:8000 --workers 2`, no `--reload`
- `docker-compose.yml`: `mysql:8` with no published port, web published as `127.0.0.1:18000:8000` because another service already uses host port 8000 on the machine where this was brought up. Inside the container the app and the healthcheck still use port 8000
- web starts after `mysqladmin ping`. `GET /healthz` runs `SELECT 1` and returns 200 `{"status":"ok"}` or 503
- uploads volume mounted at both `UPLOAD_FOLDER` and `FILE_FOLDER`
- `initial_admin.sql` is not mounted and is not loaded. `apache_conf` is not the server

`apache_conf` remains a historical HTTP vhost: `WSGIScriptAlias`, `Options Indexes FollowSymLinks MultiViews`, Apache 2.2 `Order allow,deny` / `Allow from all`, no TLS. Do not point a host at it.

`setup.py` is still the 2015 venv dump (`iggybase_env.lib.python3.4.site-packages.*`). It is unused. Leave it unused.

`readme` explains Compose startup, `/healthz`, and how to create the first account. A fresh database has empty admin tables. `/register` cannot create that first account: it needs a public facility and a public organization, and new accounts start unverified. Password reset is off (`SECURITY_RECOVERABLE` is unset, so `security.forgot_password` is not registered).

### 3.3 What is still not in the repo

These are in the repo now: `config.py`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `tests/test_sec_*.py`. Plans, spec, and requirements for the revival live under `documents/`.

Still absent:

- CI
- a migrations framework (Alembic is not used; `create_all` creates missing tables and does not alter columns)
- the live metadata that defines facility tables (only `initial_admin.sql` is checked in, and Compose does not load it)
- an API implementation (`iggybase/api/` is a scaffold)
- a first-admin seed in the image

The application cannot be understood from models.py alone. The real facility schema is the contents of `table_object` and `field` in a running database. An empty database can log in once an admin, a facility, a level named `admin`, and an organization tree including `Everyone` exist. Facility screens beyond that still need metadata. `core` is registered only when a `Module` row has `blueprint = 1` at process start.

---

## 4. Architecture

### 4.1 Top-level layout

```
LIMSbase/
  run.py, iggybase.wsgi, setup.py, requirements.txt, readme
  config.py, .env.example    # settings from the environment; .env is gitignored
  Dockerfile, docker-compose.yml, .dockerignore
  apache_conf                # historical vhost, not the server
  initial_admin.sql          # not loaded by Compose
  documents/                 # revival PRD, plans, spec, requirements
  tests/                     # MySQL-backed security tests
  make_fields.py             # utility to emit field rows from models
  dupe_roles.py              # copy role-permission rows between roles
  files/                     # uploaded operational files (charge methods)
  scripts/                   # ETL / migration / Illumina / Murray genotypes
  iggybase/
    iggybase.py              # create_app, security, registration, hooks
    database.py              # engine, session, IggybaseBase
    models.py                # dynamic lab models (TableFactory)
    tablefactory.py          # metadata → SQLAlchemy class
    cache.py                 # in-process versioned SimpleCache
    utilities.py             # get_table, filters, dates, file allowlist
    g_helper.py              # request-local RAC / OAC
    extensions.py            # mail, login manager, bootstrap
    base_routes.py           # index / home / 403 / 404
    admin/                   # metadata + identity models
    core/                    # generic engine
    web_files/               # form generator, parser, page template
    billing/
    murray/
    smallmolecule/
    sequencing/
    laboratory/
    interfaces/              # SPINAL / Harvard code check
    api/                     # empty
    templates/, static/
```

Blueprints are not registered from a static list. `configure_blueprints()` queries `Module` where `blueprint = 1` and does:

```python
bp = getattr(__import__('iggybase.' + mod.name, fromlist=[mod.name]), mod.name)
app.register_blueprint(bp, url_prefix='/<facility_name>/' + mod.name)
```

Every in-app URL is therefore:

```
/<facility_name>/<module>/<route>/...
```

Facility is a path prefix, not a subdomain. The before-request hook uses `path[0]` as the facility and `path[1:3]` as the route key.

### 4.2 Application factory

`create_app()` in `iggybase/iggybase.py`:

1. Load `Config` from the environment
2. Attach `Cache()` to the app
3. `init_db()` — `create_all` for admin models, import `iggybase.models` (which runs TableFactory), then `create_all` again
4. Register blueprints from `Module` rows where `blueprint = 1`
5. Init the Bootstrap shim, LoginManager, Mail, Flask-Security-Too
6. Register base routes (register, new_group, welcome, index, home, `/healthz`)
7. Install `before_request` / `after_request` / error handlers
8. Install `CSRFProtect` after the hook so a rejected token can still close `g.db_session`

Two things are still unusual:

- **Import connects to MySQL.** `database.py` calls `inspect(engine)` at import. An empty database can start: `create_all` runs before the factory queries `table_object`. A database that is down at import still prevents the process from starting. After start, `/healthz` reports a later outage as 503.
- **Blueprints are data.** Adding a module is an insert into `module` plus a Python package, then a process restart. `create_app` does not watch that table.

### 4.3 The metadata engine

This is the heart of the system.

#### 4.3.1 Shared row shape — `IggybaseBase`

Every table, admin or lab, inherits a common column set from `database.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | Surrogate key |
| `name` | String(100), unique | Human/business key; auto-generated |
| `description` | String(255) | |
| `date_created` | DateTime | `utcnow` default |
| `last_modified` | DateTime | default only; not auto-updated on change |
| `active` | Boolean | Soft delete |
| `organization_id` | FK → organization | Tenancy |
| `order` | Integer | Display / sort |

Table names are inferred from the class name by camel-case → snake-case (`TableObject` → `table_object`). Engine is InnoDB.

This convention is applied universally. It is why generic queries, generic forms, and generic “new name” generation work. It is also why every table is soft-deletable and org-scoped, including metadata tables.

#### 4.3.2 Metadata tables (admin)

The important ones:

| Table | Role |
|---|---|
| `table_object` | A table the engine knows about. Prefix, next id, display name, `admin_table`, `extends_table_object_id`, `note_enabled` |
| `field` | A column: data type, length, unique, default, select list, FK target, FK display field |
| `data_type` | Maps to SQLAlchemy types (`String`, `Integer`, `Boolean`, `DateTime`, file, numeric, …) |
| `table_object_role` | Whether a role can see a table; per-role display name |
| `field_role` | Per-role visibility, required, searchability, permission |
| `table_object_children` | Parent → child with the linking field |
| `table_object_many` | Many-to-many via a link table |
| `table_object_dynamic_link` | Dynamic child table chosen by a field value |
| `page_form` | A screen definition (template, title, parent inheritance) |
| `page_form_button` + role + context | Buttons on a screen, by role and context |
| `page_form_javascript` | Extra JS for a screen |
| `table_query` + render + fields + criteria + calculation | Saved queries that drive summaries |
| `route` + `route_role` | URL paths allowed for a role |
| `menu` + `menu_role` | Recursive nav |
| `module` + `module_facility` | Which Python blueprints a facility gets |
| `workflow` + `step` + `workflow_role` | Multi-step processes |
| `action` + `action_step` + `action_table_object` + `action_email` | Event hooks: import a function, send mail |
| `work_item_group` + `work_item` | A running workflow instance and the rows it points at |
| `select_list` + `select_list_item` | Enumerations |
| `permission` | Referenced by `field_role.permission_id` |

Facility-specific columns on `facility`: banner image/title/subtitle, CSS file, `table_suffix` (used to pick the extension table, e.g. `sample_smms`), `root_organization_id`, `public`.

#### 4.3.3 TableFactory

`iggybase/tablefactory.py` + `iggybase/models.py`:

1. Query all non-admin `table_object` rows, with aliases for extension/extended.
2. For each table, query its `field` + `data_type` rows.
3. Skip the eight predefined base columns.
4. For each remaining field, emit a SQLAlchemy `Column` of the mapped type.
5. If the field has a foreign key, also emit a `relationship`.
6. If the table extends another, set `id` as a FK to the parent and `polymorphic_identity`.
7. If the table is extended, set `polymorphic_on` to a `type` column.
8. `types.new_class(class_name, (base,), {}, lambda ns: ns.update(classattr))`
9. Stuff the class into `iggybase.models` globals.

Data-type mapping is partly by `data_type.name` (`getattr(sqlalchemy, datatype_name)`) and partly by magic ids:

- `data_type_id == 6` → file → `String(250)`
- `data_type_id == 8 or 9` → `Numeric(10, 2)`
- `data_type_id == 2` → `String(length)`

Hardcoded type ids are a maintenance hazard. The rest of the factory is the reason a facility can add a table without a deploy.

**Startup coupling.** Because this runs at import, the web workers, `shell.py`, and any script that imports `iggybase.models` all need a reachable database with consistent metadata. There is no generated `models_gen.py` to check in. Diffing schema changes means diffing SQL dumps or clicking through the admin UI.

#### 4.3.4 Name generation

`TableObject.get_new_name()`:

```
if prefix and new_name_id:
    name = prefix + str(new_name_id).zfill(id_length or 6)
    new_name_id += 1
else:
    name = table_name + str(random.randint(1e9, 9999999999))
```

Used everywhere new rows are created: form save, `insert_row`, work items, registration. Prefixes produce names like `CM000001`, `F000061`.

This is not atomic. The increment happens on the in-memory ORM object. Two concurrent requests can mint the same name. The unique constraint on `name` will then fail one of them, or (if the increment is committed late / not at all) names will collide later. The correct pattern is an atomic `UPDATE … SET new_name_id = new_name_id + 1` (or a MySQL sequence / dedicated counter table) inside the same transaction as the insert.

### 4.4 Access control

Two classes, constructed on every authenticated request and cached on `g`:

#### 4.4.1 `RoleAccessControl` (`core/role_access_control.py`)

Responsibilities:

- Resolve `current_user` → `User` → `current_user_role_id` → `Role` → `Facility` + `Level`
- If `current_user_role_id` is null, pick the first available `UserRole` and persist it
- Build `self.facilities`: facility name → top role + all role ids the user has there
- Load allowed routes (`Route` ⋈ `RouteRole` ⋈ `Module` ⋈ `ModuleFacility`) into `session['routes']`
- Answer: table queries, calculation fields, table-query fields, menus, page forms, page buttons, page JS, `has_access(auth_type, criteria)`, `get_table`, child/many link tables, workflow + steps, change role, change user

Route check used by `before_request`:

```python
route = '.'.join(path[1:3])   # e.g. 'core.summary'
return route in self.routes
```

Denied routes abort 404, not 403. That hides existence but also makes “not authorized” look like “does not exist.” `page_not_found` even renders a template named `not_authorized`.

`change_role` verifies the user actually has the requested `user_role`, commits the new `current_user_role_id`, and re-inits RAC (including routes).

`change_user` does **not** call Flask-Login. It looks up a user who shares a facility role and returns that user so the caller can swap org context. Combined with `make_user_menu` (a “Change User” submenu of every user who has one of the current facility’s roles), this is impersonation of data scope.

`__del__` rolls back the session. Destructors with DB side effects are a known source of vanished commits.

#### 4.4.2 `OrganizationAccessControl` (`core/organization_access_control.py`)

Responsibilities:

- Compute `org_ids` the current user may see, plus `current_org_id`
- All data-plane reads and writes for lab tables should go through this class

Org resolution:

1. Always include the `Everyone` org.
2. Load `user_organization` rows for the user.
3. Walk each org up to `facility.root_organization_id`, recording depth.
4. Pick `current_org_id` as the “lowest” (numerically smallest level) user org that is not the user’s own `organization_id`. The code itself has a TODO: it is unclear whether this should be `level.id` or `level.order`.
5. Recursively collect descendant orgs (only descending through orgs that themselves have children, via a precomputed parent-id set).
6. Cache `{current_org_id, org_ids}` in `session['org_id']` unless `?set_orgs` is present.

This logic is the most complicated part of the request path and is acknowledged as confusing in-source. It also issues a query per ancestor while walking to root (`print` of every org id is still in the walk).

Data-plane methods:

- `get_instance_data` — org-filtered get-or-new
- `get_table_query_data` — the big dynamic SELECT that powers summaries
- `get_row` / `get_row_multi_tbl` / `get_record` — **org filter is optional and defaults off**
- `get_search_results` — `LIKE %value%`, org-filtered
- `save_data_instance`, `insert_row`, `update_rows`, `update_obj_rows`
- `get_line_items`, `get_price`, `get_charge_method` — billing
- work-item helpers, action lookups

`get_table_query_data` is ~160 lines of join/alias/where assembly. It:

- aliases FK tables so the same table can be joined twice
- optionally wraps displayed values in `<a href="…">` **in SQL**
- applies `GROUP_CONCAT`-style `func.ifnull(getattr(func, field.group_func)(col.op('SEPARATOR')(', ')))`
- adds `organization_id IN org_ids` and `active = 1` on non-FK tables
- special-cases `user` so you can always see yourself
- builds a composite `DT_RowId` of `table-id|table-id|…` for DataTables

It is the most important query in the system and one of the hardest to change safely.

### 4.5 Request lifecycle

```
HTTP
  → Apache / mod_wsgi
    → create_app() (once per process)
    → before_request
         g.user = current_user
         g.db_session = db_session()
         if authenticated:
             g.rac = RoleAccessControl()
             g.oac = OrganizationAccessControl()
             ignore static/logout/favicon/welcome/registration_success/home
             else require /<facility>/<module>/...
             if path[0] is not current facility:
                 change_role to that facility’s top role, or 404
             if route not in rac.routes: 404
    → view (blueprint)
    → after_request: g.db_session.close()
```

Notes:

- Unauthenticated requests still run the hook but skip RAC/OAC. Routes without `@login_required` therefore have no org or role context.
- `print('before_request:' + elapsed)` and similar prints in OAC/summary are still live. They go to the Apache error log on every request.
- `g.db_session` is a scoped session. RAC and OAC also call `g.db_session` / `db_session()` themselves. Destructors roll it back.

Home-page resolution (`base_routes.home`): user.home_page, else role.default_home, else `core.detail` of the user row.

### 4.6 Generic UI engine

#### Page templates

`web_files/page_template.py` (via `FormGenerator` subclass) loads a `page_form` by name, inherits blank fields from ancestors, loads role-filtered buttons and javascript, and builds the navbar/sidebar from `menu` / `menu_role`.

The `@templated` decorator plus `PageTemplate.page_template_context()` is how almost every screen gets a consistent chrome.

#### Summaries

`core.summary` / `action_summary` / `workflow`:

1. `TableQueryCollection(table_name)` loads the `table_query` attached to this route+role+table.
2. The HTML page renders an empty DataTable.
3. `/summary/<table>/ajax` builds or cache-hits a JSON payload `{data: rows}`.

Cache key: `route|role_id|current_org_id|table_name`. Criteria and query-string filters are **not** part of the key (there is a TODO). Cache TTL is 24 hours for unfiltered summaries, invalidated by a crude per-table version integer on the in-process `SimpleCache`.

`action_summary` is a summary plus bulk actions (pass/fail QC, receive oligos, generate invoices).

#### Detail

`/detail/<table>/<row_name>`: one `TableQueryCollection` with a name criterion. No fields → 404. No row → 403.

#### Data entry

`/data_entry/<table>/<row_name>`:

1. `FormGenerator` builds a WTForms class from the instance graph (`InstanceCollection`, default depth 2, or 0 for `new`).
2. GET renders the form.
3. POST validates CSRF, `FormParser.parse()` maps fields onto instances, `fp.save()` commits and stores uploads.

Field names:

```
data_entry-{table}-{field}-{instance_id_or_name}-{row_index}
files_data_entry-…
bool_data_entry-…     # checkbox companion
id_data_entry-…       # FK numeric id next to a lookup
```

`multiple_entry` is the same engine over a JSON list of names. After regenerate-on-POST it **deletes the csrf_token error** because the new form has a new token. That is a known CSRF weakening.

`modal_add` / `modal_add_submit` is the same engine without a CSRF check on submit.

#### Form parser details

`FormParser` (`web_files/form_parser.py`):

- Instantiates `InstanceCollection` from `max_depth`, `main_table`, `base_instance`
- Iterates `request.form`, matches the field regex
- Coerces types: int, bool (`yes/y/True/1/on`), datetime, date, float, Decimal, FK (int or lookup), file
- Collects required-field errors only for instances that will be saved
- On save: `instances.commit()`, then write files under `UPLOAD_FOLDER/<table>/<row_name>/` using `secure_filename`
- File values are `|`-joined filenames stored on the row

File handling has a bug in the allowlist check: it uses `self.files[key].filename` before `self.files` is populated that way (`request.files[key]` is a `FileStorage` / multi-dict). Depending on Werkzeug version this either errors or checks the wrong object.

#### Workflows

`Workflow` loads `workflow` + `step` (route, module, optional table, optional dynamic field, optional `params` of the form `key=value`).

`WorkItemGroup` is a running instance. `/workflow/<name>/<step>/<wig>`:

1. Run before-actions
2. If `new`, create and redirect to step 1
3. If form posted `next_step` / `complete`, save work items, run after-actions, redirect
4. Otherwise dynamically import the step’s view (`globals()[route]` or `iggybase.<module>.routes.<route>`) and call it with `wig.dynamic_params`
5. Wrap the result in `work_item_group.html` with extra buttons

This is a real workflow engine. The dynamic dispatch is powerful and is also how a metadata row chooses arbitrary Python to run.

#### Actions

`core/action.py` is the hook system:

- **Step actions** — before/after a workflow step
- **Table actions** — on insert/update of a table, optionally when a field matches a compare
- **Named actions** — from action-summary buttons

An action row stores `namespace`, `function`, JSON `fixed_parameters`, `return_values`, and optional `ActionEmail`. Execution is:

```python
action_module = import_module(namespace)
action_method = getattr(action_module, function)
return_values = action_method(*args, **kwargs)
```

Then optionally `send_mail`. Recipients can contain `<position>` tokens that should expand to users with that position in the current or root org.

This is a plugin mechanism. It is also RCE if an attacker can edit `action`.

### 4.7 Caching

`iggybase/cache.py` wraps Werkzeug `SimpleCache`:

- Per-process, in-memory, not shared across the 15 WSGI threads/processes
- Optional “refresh on table X” via a version suffix on the key
- Versions are integers 1–100, then wrap to 1. After 100 writes, stale entries can match again
- `lower_list` does `for obj in objs: obj = obj.lower()` and returns the **original** list. Version keys are case-sensitive. `increment_version(['Order'])` will not invalidate `'order'`
- `/core/cache/` is a logged-in UI to get/set keys and versions

For a 15-thread daemon this cache is more likely to serve stale or inconsistent summaries than to help.

### 4.8 Dynamic function lookup

`utilities.get_func(module_name, func_name)` is a generic `import_module` + `getattr` used by calculations and actions. `utilities.get_table(name)` looks up `table_object`, then imports either `iggybase.admin.models` or `iggybase.models` and `getattr`s the camel-cased class. Missing tables abort 403.

This is consistent with the “everything is metadata” philosophy. It also means table names from the URL become import paths, so `get_table` / `rac.get_table` are load-bearing authorization checks. They must stay in front of every dynamic access.

---

## 5. Domain modules

### 5.1 Billing

The second-most important package.

**Data.** Line items point at orders, price items, invoices. Orders have submitters, charge methods (with percents), and a billable flag. Price lists are per `organization_type`. Organizations have mailing and billing addresses, institution, department.

**Review** (`/billing/review/<year>/<month>`). Table query of line items in the month with `price_per_unit > 0`.

**Invoice collection.** `InvoiceCollection` groups `oac.get_line_items(...)` into per-org invoices. `Invoice` computes totals, charge-method splits, user grouping, and a PDF name:

```
{FACILITY_SUFFIX}{SERVICE_PREFIX}IG{ORG_TYPE}-YYMM-{NN}
```

`IG` is an iggybase marker. `core_prefix` maps `bauer` → `SC`, `helium` → `HU`. Letterhead is hardcoded Harvard FAS / Northwest Lab.

**Generation.** `generate_invoices` accepts an optional org list, updates PDF names in the DB first (comment: WeasyPrint “borks the db_session”), then writes PDFs. `invoice_pdf` renders `invoice_base.html` through WeasyPrint.

**Pricing API.** `/billing/get_price/ajax` — looks up `price_list` by current org’s `organization_type_id` and a `price_item_id`.

**Known billing fragility.**

- `get_line_items` uses a mix of inner and outer joins specifically so missing reference data becomes a visible error rather than a silently omitted charge. That is the right instinct.
- `get_users_by_position` is broken (see §7), so invoice emails that expand `<manager>` will not find anyone.
- WeasyPrint / session interaction is a known landmine.

### 5.2 Murray (oligo core)

Thin, well-scoped, and a good example of how the generic engine is supposed to be extended:

| Route | Filter | Bulk update |
|---|---|---|
| `update_requested` | oligo.status = requested | status → Ordered, set `ordered=now` |
| `update_ordered` | oligo.status = ordered | status → Received, set `received=now` |
| `cancel` | oligo.status in (ordered, requested) | status → Canceled |

Each page is a `TableQueryCollection` plus hidden JSON for `column_defaults`, `button_text`, and `message_fields`. The actual update goes through `core.update_table_rows`.

### 5.3 Small molecule

- QC action-summary for `test_smms` pending / pass / fail
- `LipidAnalysis`: read vendor TSV/CSV, compute retention-time means (`numpy.mean` of `GroupTopPos`), key rows by `LipidIon_ret_time`, classify via a hardcoded `lipidKey.csv`, emit class/subclass stats and a zip
- Paths are hardcoded under `Config.UPLOAD_FOLDER + '/lipid_analysis/'`
- A `?debug=` query flag is still present

This is real scientific code living inside a request handler. It is also the kind of thing that should be a job queue, not a web thread.

### 5.4 Sequencing

The blueprint is nearly empty. The work is in `scripts/sequencing/`:

- `illumina_script.py` walks a run directory, parses `RunInfo.xml`, inserts run rows
- `line_item_script.py` generates billing line items from sequencing work
- Both inherit `IggyScript`, which opens a raw `mysql.connector` connection and builds SQL by string concatenation

### 5.5 Interfaces

One endpoint: `POST/GET /<facility>/interfaces/check_harvard_code?spinal_code=`. Queries an external SPINAL database (`spinal_db_session`) for `ExpenseCodesExpensecode.fullcode` and returns `VALID` / `NOT_FOUND` / `INACTIVE` / `EXPIRED` / `PREMATURE`. Bare `except:` returns `None`.

This is how Bauer invoices stay attached to real Harvard 33-digit codes.

### 5.6 Scripts

`scripts/` is operational knowledge that is easy to underestimate:

| Script | Purpose |
|---|---|
| `iggy_script.py` | Base CLI + raw MySQL helper (`pk_exists`, maps, inserts) |
| `insert/metadata_script.py` | Load / sync metadata |
| `migrate/migrate_script.py` + `migrate_custom_script.py` | Data migrations, including user/address/org backfills |
| `murray/migrate_genotype.py` | Import genotypes onto strains |
| `sequencing/*` | Illumina + line items |

`IggyScript.pk_exists` interpolates values into SQL with only a single-quote escape. These scripts were run by operators, not by the web app, but they are still injection-prone and they embed a second, non-ORM access path to the same database.

`make_fields.py` and `dupe_roles.py` use `eval()` on model names to reflect columns and clone role-permission rows. They are admin utilities, not request handlers, but `eval` on anything that could be influenced is a habit to drop.

---

## 6. Identity, registration, and org onboarding

### 6.1 User model

`User` is both a Flask-Security `UserMixin` and an `IggybaseBase` row.

- `password` is a String(120) column. Flask-Security is configured against this model; the model also exposes `set_password` / `verify_password` using Werkzeug `generate_password_hash` / `check_password_hash`. Whether Flask-Security’s own hashing or these methods win depends on Flask-Security 1.7 configuration that lives in the missing `Config`.
- `is_active` requires both `active` and `verified`. New registrations force `verified = 0`, so a newly registered user cannot log in until an admin verifies them. That is the right default for a core facility.
- `current_user_role_id` is a FK to `user_role`. Role switching is a column update, not a session-only concern.
- Email is unique. Username is `name` and is also unique (via the base column).

`ExtendedLoginForm` relabels the field “Username or email.” Whether that actually searches both is a Flask-Security configuration question not visible in-repo.

`lm.login_view = 'mod_auth.login'` in `extensions.py` refers to a module (`mod_auth`) that `setup.py` still lists but the tree does not contain. Login is actually Flask-Security’s `/login`. This is a leftover from an earlier package layout. See §16 for the full `mod_auth` history.

### 6.2 Self-registration (`/register`)

Public. Creates:

1. User (unverified)
2. `UserOrganization` (default org = selected group)
3. `Address`
4. `UserRole` for the selected facility’s `User` level
5. Sets `user.address_id` and `user.current_user_role_id`

Then logs the user out and shows `registration_sucess.html` (typo shipped).

`populate_model` is supposed to copy form fields onto a new ORM object and convert `QuerySelectField` values to ids. It does not: after `new_val = new_val.id` it writes `getattr(form, val).data` (the original object) instead of `new_val`. Some fields are set explicitly afterward (`organization_id`, names), which hides the bug for those fields only.

### 6.3 New group (`/new_group`)

Public. Creates an inactive (`active = 0`), public organization under the facility root, with:

- organization type, optional department / institution
- lab-admin user (found by email or created)
- `UserOrganization` + `UserOrganizationPosition(manager)`
- mailing address, optional separate billing address (`b_` prefix)
- `same_as_above` uses a custom `ElseRequired` validator

The new org is inactive, so it should not appear in registration dropdowns until staff approve it. That is a good workflow. The same `populate_model` bug applies.

---

## 7. Defects that would fire in production

**Status on 2026-10-06: still open.** The revival did not take these. They were left because the security and library slices could proceed without them. A fresh read of the same sites (`populate_model`, `get_users_by_position`, `send_mail`'s discarded `str.replace`, `ActionEmail.id == Action.id`, the `oganization` typo, class-attribute `UniqueConstraint`s, cache behavior, inverted `check_facility`, racy names, `__del__` rollbacks, `update_table_rows`, the file-parser allowlist check, `last_modified`, and `InstanceCollection` iteration) still matches the code below.

These are not style nits. They look like defects that would have affected real users, invoices, or data integrity.

### 7.1 `populate_model` discards FK conversion

```python
if hasattr(new_val, 'id'):
    new_val = new_val.id
setattr(obj, key, getattr(form, val).data)  # object, not new_val
```

Registration and new-group write ORM objects into integer columns for any field that is *only* handled by this helper.

### 7.2 `get_users_by_position` filters the wrong column, twice

```python
.filter(models.UserOrganizationPosition.active == org_id)
.filter(models.UserOrganizationPosition.active == active)
```

The first predicate should be `organization_id`. The second then requires `active == 1`. Together they ask for `active == org_id AND active == 1`, which is almost never true. Invoice / action emails that expand `<lab manager>` will send to nobody.

`UserOrganizationPosition` as modeled also has `user_id` and `position_id` but **no `user_organization_id` / `organization_id` column in the class body**, while `new_group` writes `user_organization_id`. Either the live DB has columns the model is missing, or those writes are being silently ignored. Both are bad.

### 7.3 `send_mail` throws away the substitution

```python
value.replace('<' + position + '>', position_email[:-1].strip())
```

`str.replace` is not in-place. `value` is unchanged. Recipients stay the literal token. Combined with 7.2, action email is very likely non-functional for position-based addressing.

The next line also calls `get_users_by_position(instance.organization_id)` *without* a position name when an instance is present — argument order is `(position, org_id=None)`. A numeric org id is passed as the position string.

### 7.4 `ActionEmail` joined on `id == id`

```python
.outerjoin(models.ActionEmail, ActionEmail.id == Action.id)
```

Should be `ActionEmail.action_id == Action.id`. Repeated in `get_action`, `get_step_actions`, `get_table_object_actions`. Email rows will only attach when the two surrogate keys happen to collide.

### 7.5 Typo: `oganization`

```python
if fk_table_data.name == 'oganization':
```

The special case that should filter organizations by `id IN org_ids` never runs. Org dropdowns use the generic `organization_id IN org_ids` path, which is the wrong column for the organization table itself.

### 7.6 `UniqueConstraint` assigned as a class attribute

```python
role_unq = UniqueConstraint('facility_id', 'level_id')
```

SQLAlchemy only honors this inside `__table_args__`. Same pattern on `RouteRole`, `MenuRole`, `TableObjectRole`, `FieldRole` (`unique` even references a `page_id` column that is not on the class). Constraints may exist in `initial_admin.sql` or in the live DB; the ORM does not own them. `create_all` on a fresh DB will not create them.

### 7.7 Cache invalidation is broken

- `lower_list` does not lowercase list contents
- versions wrap at 100
- `SimpleCache` is per-process
- filter/criteria are omitted from the summary cache key

Summaries can be stale, shared across filters, or split across workers.

### 7.8 `check_facility` / `check_facility_module` invert the boolean

They `return rec is None`. Callers that treat truthy as “allowed” have it backwards. Several of these helpers also appear unused (`check_url3`), which is itself a smell.

### 7.9 Name generation is racy

See §4.3.4. Unique `name` will turn races into user-facing IntegrityErrors rather than silent corruption, but “save failed, try again” on new samples is still a production incident.

### 7.10 Destructor rollbacks

`RoleAccessControl.__del__` and `OrganizationAccessControl.__del__` call `self.session.rollback()`. If a view has committed, and a later exception triggers GC of these objects on a shared scoped session, the next unit of work can be surprising. If a view has *not* committed, `__del__` can roll back work the caller still holds.

### 7.11 `update_table_rows` matches ids independently per table

The handler splits `DT_RowId` values (`order-12|line_item-44`) into per-table id lists, then applies criteria as `id IN (...)` **per table independently**. The in-source TODO is explicit: this updates any row whose id appears, not the specific combinations selected. Combined with the other TODO (“protect this by checking the rows against org_ids”), bulk update is both too broad and under-authorized.

`oac.update_rows` *does* filter by `organization_id IN org_ids`. `update_table_rows` goes through `TableQuery.update_and_get_message`, which needs a careful read before any revival; the route-level comment says the author did not trust it.

### 7.12 File parser allowlist check

```python
if request.files[key] and util.allowed_file(self.files[key].filename):
```

`self.files[key]` is not how the dict is populated (`self.files[(instance_name, table_name)] = []`). This is either a TypeError or a check against the wrong object, depending on execution path.

### 7.13 `last_modified` is not maintained

The base column defaults to `utcnow` on insert and is never set to “now” on update (except when a form explicitly includes it). Anything that sorts or filters on `last_modified` as “last edited” is wrong.

### 7.14 `InstanceCollection.__iter__` / `__getitem__`

```python
def __iter__(self, table_name):
def __getitem__(self, table_name, instance_name):
```

These do not match the Python data-model signatures (`__iter__(self)`, `__getitem__(self, key)`). They cannot work as documented. Callers that use them as mappings will fail.

---

## 8. Security review

A LIMS holds identified research data, user PII (names, emails, addresses, phones), and billing instruments (Harvard 33-digit codes, charge methods). The bar is not “internal tool.”

**Status on 2026-10-06.** The high findings in §8.1 through §8.8 were closed in code and covered by `tests/test_sec_*.py` against MySQL. §8.9 and §8.10 and §8.12 changed with the new stack and Compose. §8.11 and §8.13 were not taken. The original write-up is kept under each heading so the defect is still visible, then a status line says what the code does now.

### 8.1 Unauthenticated search — high

**Status: fixed.** Both routes have `@login_required`. `tests/test_sec_search.py`. An anonymous search redirects to `/login`.

```python
@core.route('/search', methods=['GET', 'POST'])
def search(facility_name):
    ...
@core.route('/search_results', methods=['GET', 'POST'])
def search_results(facility_name):
```

No `@login_required`. `before_request` does not construct RAC/OAC for anonymous users. `ModalForm` then runs whatever lookup `search_vals` describes.

### 8.2 Generic row fetch with org filter off — high

**Status: fixed for this route.** `get_row` requires login, checks `RoleAccessControl.has_access` for the table, and loads with `organization_id IN org_ids`. An empty `org_ids` list uses `false()` because `IN ()` is invalid SQL. `get_price` uses the same org rule. The default of `OrganizationAccessControl.get_row` stays unscoped for other callers. `tests/test_sec_row.py`.

```python
@core.route('/get_row/<table_name>/ajax')
def get_row(...):
    row = oac.get_row(table_name, criteria)  # org_filter=False
```

Any authenticated user who can reach `core.get_row` can read arbitrary columns from any table `get_table` will resolve, by any equality criteria the client sends. That includes admin tables if they are registered as `admin_table`.

### 8.3 Impersonation / org-scope switch — high

**Status: partially fixed.** `caller_is_admin()` is true only when the current role's level name strips and lowercases to exactly `admin`. Any other caller gets `success` false and the session org is left alone. A successful switch writes one `iggybase.audit` info line with actor id, target id, facility name, and a UTC timestamp. The line does not include the request body, a password, or the session cookie. `tests/test_sec_change_user.py`.

What remains is the design: an admin still recomputes `org_ids` as the target user. There is no time box and no banner. `make_user_menu` is commented out in `page_template.py`. This is not yet a separate impersonation session.

`POST /core/change_user` with `{user_id}`:

1. Requires only that the target user shares a facility role with the caller
2. Does not re-bind Flask-Login
3. Recomputes `org_ids` as the target user

A facility admin (or anyone granted the route — it is metadata) can browse another PI’s entire org tree. There is no audit log, time box, or banner.

`make_user_menu` exposes the full user list in the chrome.

### 8.4 File download is not org-checked — high

**Status: fixed.** `file_row` and `file` load the owning row with `get_row(..., org_ids=oac.org_ids)` before `send_from_directory`. A missing or out-of-org row is an empty 404. `safe_join` keeps the table and row under `FILE_FOLDER`. `tests/test_sec_files.py`. Charge-method files under `files/` are still in git.

```python
@core.route('/files/<table_name>/<row_name>/<filename>')
def file_row(...):
    return send_from_directory(FILE_FOLDER / table_name / row_name, filename)
```

Authorization is “logged in.” `send_from_directory` prevents `../` escape, but any authenticated user who can guess or enumerate `table/row/filename` gets the file. Charge-method PDFs and CSVs are already in the git tree under `files/`.

### 8.5 Stored XSS in summaries — high

**Status: fixed in the summary and save-message paths that were in scope.** Anchors are no longer built in SQL. `TableQuery.format_results` escapes link text and URLs with `markupsafe.escape` before wrapping them in an anchor. A download (`allow_links` false) keeps the raw value. `saved_data` escapes the visible name and the href. Templates still mark `page_msg` and summary cells safe because the user value is escaped first. `tests/test_sec_html.py`. The client still receives HTML, not a `{text, href}` object. Search modal field names are escaped the same way.

```python
col = ('<a href="' + link + col + '">' + col + '</a>')
```

This is assembled in SQL and returned as DataTables JSON. Sample names, oligo names, descriptions — anything a user can type into a linked field — become HTML. A lab user can attack a facility admin who opens a summary.

Fix: return a structured `{text, href}` and let the client or Jinja escape.

### 8.6 CSRF gaps — medium / high

**Status: fixed for state-changing requests that Flask-WTF checks.** `CSRFProtect` is installed in `create_app` after `configure_hook`, so `g.db_session` exists when a missing token is rejected and the view does not run. A missing or invalid token is a 400. GET, HEAD, OPTIONS, and TRACE are not checked. `base.html` exposes `csrf-token`. `main.js`, `action_summary.js`, and `billing_summary.js` send `X-CSRFToken`. `multiple_entry` calls `validate_csrf` before `FormParser.save` and does not delete the token error to skip that check. `tests/test_sec_csrf.py` keeps CSRF enabled.

`data_entry` still calls `fg.form_class.validate_csrf_data(...)`. That method is not on the form class. A POST that already passed `CSRFProtect` can then raise `AttributeError`. That call was not rewritten. `modal_add_submit` still has no extra check of its own; `CSRFProtect` covers the POST.

Checked: `data_entry` POST (explicit `validate_csrf_data`).

Not checked:

- `modal_add_submit`
- `update_table_rows`
- `change_role`
- `change_user`
- `generate_invoices`
- `get_row` / `get_price` (state-changing depending on caller)

`multiple_entry` validates CSRF, then **deletes** the `csrf_token` error after regenerating the form. That is equivalent to “CSRF optional on the second pass.”

JSON POSTs in Flask-WTF 0.12 are easy to get wrong; these endpoints read `request.json` with no token.

### 8.7 Cache administration — medium

**Status: fixed for the write path and the role check.** `/core/cache/` aborts 403 unless `caller_is_admin()`. The set-key and set-version branches are gone, so those posts do not call `cache.set` or `cache.set_version`. An admin can still read a key. `tests/test_sec_cache.py`. The cache is still in-process `cachelib.SimpleCache`, so the staleness notes in §7.7 remain.

`/core/cache/` is a logged-in form that gets and sets arbitrary cache keys and version numbers. It is not role-restricted in code (only via `route_role` metadata). Combined with the summary cache, an attacker can plant a JSON payload that a summary page will serve to other users (XSS amplifier) or force versions that resurrect stale data.

### 8.8 Dynamic import from the database — high if admin is compromised

**Status: fixed for action hooks and workflow step imports.** `iggybase/core/action_allowlist.py` allows `iggybase.core.actions` functions `add_record`, `update_record`, and `initiate_billing`. `execute_action` and `get_func` import only a pair on that list. Anything else is logged and not imported. Workflow step imports go through `import_step_routes`, limited to `core`, `billing`, `murray`, `smallmolecule`, `sequencing`, `laboratory`, `admin`, and `interfaces`. `tests/test_sec_actions.py`.

Not on that allowlist, and not changed: `get_calculation`'s `__import__`, and `utilities.get_table` / `get_table` inside role access control via `import_module`. `get_action`'s `ActionEmail` outer join still compares `ActionEmail.id` to `Action.id` and does not return the email row on SQLAlchemy 2. The test loads the action row itself. `initiate_billing` still has `return return_values.update(results)`, which returns `None`.

`Action.namespace` + `Action.function` are `import_module`’d and called. Anyone who can edit `action` (or SQL-inject into it via a script) has RCE in the web worker.

Mitigation if the engine is kept: allowlist `(module, function)` pairs in code.

### 8.9 End-of-life dependencies — high

**Status: fixed by replacement.** The process is Python 3.14 with the pins in §3.1. The old sentence below describes the tree as it was. Those versions are no longer installed.

Python 3.4, Flask 0.12, Jinja2 2.9, Werkzeug 0.12, Pillow 4, WeasyPrint 0.36, html5lib 0.999999999. Public CVEs exist across this set (Flask/Jinja XSS and sandbox issues, Pillow image bombs, old Werkzeug debugger risks). Even a “private” core-facility server on the Harvard network is a poor place for this combination in 2026.

### 8.10 Transport and Apache config — medium

**Status: the checked-in vhost is no longer how the app is served.** Compose publishes `127.0.0.1:18000` only. gunicorn listens on `8000` inside the container. There is no TLS terminator in this repo. `apache_conf` is unchanged and still has `Options Indexes`, `FollowSymLinks`, and `Allow from all`. Do not deploy that file.

Checked-in vhost is HTTP, directory indexes on, `Allow from all`, `FollowSymLinks`, logs and the WSGI file inside the document root pattern (`/var/www/html/iggybase`). `Options Indexes` on a LIMS is how `files/` and `iggybase.log` get listed.

### 8.11 Scripts use string-built SQL — medium (ops path)

**Status: still open.** Not part of the revival.

`IggyScript.pk_exists` and the migrate/Illumina scripts interpolate identifiers and values. These run with DB credentials from `Config`. A hostile filename or RunInfo field is a plausible injection if a script is pointed at untrusted input.

### 8.12 Password and session notes

**Status: updated.** `lm.session_protection = 'strong'` remains. `SECRET_KEY` and `SECURITY_PASSWORD_SALT` come from the environment. New accounts use `flask_security.utils.hash_password` (argon2). `User.password` is `String(255)`. `fs_uniquifier` is a non-null unique `String(64)`. `User.is_active` is true only when `active` and `verified` are both true. `User.set_password` still calls Werkzeug `generate_password_hash` and is not the path the readme uses for the first account. Legacy hashes were not preserved; the first database is empty. Password reset stays off.

- `lm.session_protection = 'strong'` is good.
- Secret key is in external `Config` — fine, as long as it was not reused and is long enough.
- Flask-Security 1.7 password hashing / token salts should be treated as legacy. On revival, re-hash on login.
- `User.password` is 120 chars; some modern hashes are longer.

### 8.13 Information disclosure

**Status: still open.** The revival did not remove these prints or the route-map log line. `change_user` now has the audit line in §8.3. Denied routes still return 404. The 403 and 404 handlers still require login, and they need `PageForm` rows (`forbidden`, `not_authorized`) plus `AdminNavBar` and `AdminSideBar` menu rows or the error template raises while rendering.

- Denied routes return 404, which is reasonable.
- 403/404/500 handlers require login, so anonymous users hitting a missing page get a login redirect rather than an error page. Fine.
- `logging.info` of full route maps, user names, and SQL compiles (commented but present) will land PII in `iggybase.log`.
- `print` of org ids on every OAC miss is noisy and leaks structure to error logs.

### 8.14 What is actually in good shape

- Parameterized SQLAlchemy for the web data path (the LIKE search does not concatenate raw SQL; `%` / `_` are just not escaped as literals).
- `secure_filename` on uploads (when that branch runs).
- New accounts start unverified.
- New groups start inactive.
- Generic data queries that *do* go through `get_table_query_data` / `get_instance_data` apply `organization_id IN org_ids`.
- Soft deletes (`active`) rather than hard deletes for most data.
- CSRF present on the primary data-entry form.

The engine wanted to be careful. Search, `get_row`, files, non-admin `change_user`, cache writes, summary HTML, and unbound action imports were the edges that got code and tests. Bulk update (`update_table_rows` still carries the org-check TODO), `modal_add_submit`, script SQL, and the §7 defects are the edges that remain.

---

## 9. Code quality and maintainability

### 9.1 What reads well

- Package layout matches the domain.
- RAC vs OAC is a clean conceptual split.
- Murray is a model plugin: a few routes, no forked engine.
- TODOs are honest and still accurate.
- Billing joins are written to fail visibly rather than drop charges.
- `IggybaseBase` as a universal row shape is a strong convention.

### 9.2 What does not

**Tests cover the security slices only.** `tests/test_sec_search.py`, `test_sec_row.py`, `test_sec_files.py`, `test_sec_change_user.py`, `test_sec_csrf.py`, `test_sec_html.py`, `test_sec_cache.py`, and `test_sec_actions.py` each use their own MySQL schema (`iggybase_sec` through `iggybase_sec8`). They do not mock the organization filter. There is still no test for the org-tree walk outside those fixtures, the form parser, name allocation, or invoice totals. A change outside those eight files is still a production experiment.

**Debug left in the request path.** `print('before_request:…')`, `print('oac init:…')`, `print('cache miss')`, `print('rollback')`, `print('extra')` during the org walk. Unchanged.

**Bare `except:`** in save/insert/SPINAL/get_func. Failures become a log line and `None`.

**Inconsistent style.** Spaces inside parentheses (`create_app( )`), mixed `filter_by` / `filter`, mixed Python 2 comments (`#python3`, `#if isinstance(pk, basestring)`). `flask.ext.*` imports are gone from `iggybase/`. `setup.py` still names `flask.ext` inside the unused freeze. `from flask_wtf import Form` is WTForms' `Form`; the code imports `FlaskForm` by name.

**Dead or half-built packages.** `api/` empty. `laboratory/` empty. `admin/decorators.py` and `admin/views.py` thin. `mod_auth` referenced but gone.

**Vendor trees in git.** `static/jquery/DataTables/` includes examples, PHP server-side demos, extensions, and contributing docs. `bootstrap_datepicker/locales/` has ~60 languages. This dominates file count and hides the actual application.

**`setup.py`.** A dump of a 2015 venv. Not salvageable; replace with a 10-line `pyproject.toml`.

**Typos that shipped.** `registration_sucess.html`, `oganization`, `automoatically`, `refacotr` in a commit message.

**Harvard-specific constants in library code.** Invoice address, `core_prefix`, SPINAL. Fine for one campus; they block any second tenant.

### 9.3 Complexity hotspots (change-risk)

| File | Why it is expensive |
|---|---|
| `core/organization_access_control.py` | 870 lines; query builder + org walk + billing + work items |
| `core/role_access_control.py` | 710 lines; every permission question |
| `web_files/form_generator.py` + `form_parser.py` | Dynamic WTForms + file/FK coercion |
| `core/instance_collection.py` + `instance_data.py` | Save graph, history, actions |
| `iggybase.py` | App factory + registration + hooks + forms in one file |
| `admin/models.py` | Entire metadata schema |
| `tablefactory.py` | Boot-time ORM generation |
| `billing/invoice.py` + `invoice_collection.py` | Money |

Any revival should put tests around these before moving them.

### 9.4 Documentation that exists

- `readme` — Compose startup, `/healthz`, and the first-account command. It is no longer the Python 3.4 + mod_wsgi runbook
- `documents/` — one PRD plus a plan, spec, and requirements for libraries, critical security, and Docker
- Inline comments and TODOs — still the best description of the engine
- No ERD and no data dictionary beyond `initial_admin.sql`

This file is the architecture review. The revival documents are the record of what was changed.

---

## 10. Data and operations

### 10.1 Database

Single MySQL database (`Config.SQLALCHEMY_DATABASE_URI + Config.DATA_DB_NAME`). Admin metadata and lab data share an engine and a session. Comments in `database.py` mention mimicking Flask-SQLAlchemy for Flask-Security (`DBFactory`); there is no second “admin DB” at runtime despite comments that talk about one.

`pool_recycle=3600` is the standard MySQL wait_timeout dodge.

`init_db()` calls `create_all`. That will create missing tables from current models; it will not migrate columns. Schema evolution is `scripts/migrate/*` and hand SQL.

### 10.2 Files

Uploads go to `Config.UPLOAD_FOLDER / <table> / <row_name> / <filename>`. The repo also contains `files/charge_method/CM000000/` with a real PDF, CSV, and workflow PNG. Those look like production fixtures that should not live in git (PII / contractual documents risk).

### 10.3 Logging

`logging.basicConfig` to `iggybase.log` at DEBUG, configured in `create_app` and still in the WSGI file. `sys.path` is also given a directory named `iggybase.log`, which is accidental. The image `chown`s `/app` to `iggybase` because that log is created at startup and the workdir would otherwise be root-owned.

`change_user` writes one `iggybase.audit` line on success. There is still no request id, and no audit trail for role change, invoice generation, or bulk update. The prints in §8.13 still run.

### 10.4 Processes that are not the web app

- Illumina import against `/n/seq/sequencing/`
- Murray genotype migration
- Metadata insert
- Custom migrate from a source DB (`migrate_config.from_db`)

These are the operational backbone. A revival that only ports the Flask app will strand the cores.

---

## 11. What is valuable (do not throw away)

1. **The metadata schema.** `table_object`, `field`, `*_role`, `page_form`, `table_query`, `route`, `menu`, `workflow`, `action`. This is years of product thinking. A rewrite that hard-codes tables is a step backward.

2. **The tenancy model.** Facility × role × org tree, with Everyone, public orgs, and per-facility table extensions (`table_suffix`). This matches how core facilities actually work (one PI in two cores, students under a lab, billing at the group).

3. **The generic screen triad.** Summary / detail / data-entry covering parent-child-many at configurable depth. If this works, adding a table is data, not a feature team.

4. **Workflows + work item groups.** Core-facility intake is a pipeline. Modeling it as steps over a bag of rows is right.

5. **Billing rules.** Price lists by org type, charge-method splits, invoice numbering, SPINAL code check, “don’t inner-join away a billable row.” Accounting will not want this reinvented from memory.

6. **Scripts as institutional knowledge.** Illumina, genotype, metadata loaders. These encode column mappings and dirty-data decisions.

7. **Conventions.** Everything has `id`, `name`, `active`, `organization_id`, `order`. Auto-names with prefixes. Soft delete. These conventions make the generic engine possible.

---

## 12. What to discard or replace

1. **The 2015 runtime.** Replaced. Python 3.14, Flask 3.1, flask-security-too 5.9, Werkzeug 3.1, Pillow 12, WeasyPrint 70, gunicorn. `flask.ext` is gone from application code. `setup.py` still lists the old freeze and should stay unused.

2. **Boot-time TableFactory against a live DB.** Still how models are built. Importing `iggybase` connects because `database.py` calls `inspect(engine)` at import. `/healthz` can report the database down after the app has started. The factory still runs at startup.

3. **In-process cache.** Still `cachelib.SimpleCache`. The set-key and set-version UI is gone. The read UI remains, and only an admin can open it. Redis was not added.

4. **HTML-in-SQL links.** Removed from the summary formatter. The response is still an HTML anchor, with the user value escaped first.

5. **`setup.py` as venv dump, DataTables examples, datepicker locale forest.** Still in the tree.

6. **`change_user` as an org-scope swap.** Admin-only and audited. Still not a time-boxed, bannered session.

7. **Public search and the login-only file server.** Closed. See §8.1 and §8.4. Other callers of `get_row` can still pass no `org_ids`.

8. **Action `import_module` from an arbitrary namespace.** Allowlisted. See §8.8 for the imports that were left alone.

9. **Apache 2.2 HTTP vhost with Indexes.** Still in `apache_conf`. Compose does not use it.

10. **Hardcoded FAS letterhead in invoice.py.** Unchanged. Move to `facility` or config if a second campus is ever real.

---

## 13. Revival options

### Option A — Do not revive the process; keep the model

Treat this repo as a specification. Reimplement the engine on Python 3.12 + a maintained web stack (Flask 3, FastAPI, or Django) with:

- the same metadata tables (migrate the MySQL)
- a generated or mapped ORM layer
- tests first for RAC, OAC, name allocation, form parse/save, invoice totals
- an actual API (the empty `api/` package is the missing product surface)

This is the right option if anyone still wants a configurable multi-core LIMS.

### Option B — Secure and freeze

If the only goal is “keep historical invoices readable”:

- take the app off the network
- export invoices/PDFs/CSVs
- snapshot the DB
- do not patch toward modernity

### Option C — In-place upgrade (this is what was done)

The 2015 text called this a rewrite with extra steps and did not recommend it. It is the path that was taken, on Python 3.14 rather than 3.12, and with a narrower scope than "fix every item in §7 and §8."

What landed:

- library upgrade on Python 3.14, keeping `session.query()`, the custom engine, and `DBFactory`
- §8.1–§8.8 in code, each with one MySQL-backed unittest module
- Docker Compose with gunicorn, `/healthz`, and a login page. WeasyPrint `write_pdf()` returned `%PDF-` inside the image
- secrets from the environment. New passwords are argon2. The password column is `varchar(255)`

What was left on purpose:

- every defect in §7
- §8.11 script SQL and §8.13 log noise
- `get_action`'s `ActionEmail` join, `data_entry`'s `validate_csrf_data` call, and `initiate_billing`'s `return return_values.update(results)`
- loading `initial_admin.sql` (its module names do not match the blueprint packages)
- public exposure. The published port binds to `127.0.0.1`

Option A remains the right plan if the generic screens, billing, and workflows have to be trustworthy for a second campus. Option C made the existing engine start, and closed the holes that were called high.

### Suggested order if Option A is chosen

1. Document the live metadata (dump `table_object`, `field`, role maps, workflows). This file is not a substitute for that dump.
2. Write characterization tests against a sanitized DB copy: org walk, route map, one summary, one data-entry save, one invoice total.
3. Reimplement access control with default-deny and org filter on every data path.
4. Reimplement name allocation atomically.
5. Port billing next (money is where silent bugs hurt).
6. Port workflows / actions with an allowlisted function table.
7. Re-attach Murray / SMMS / sequencing as modules.
8. Only then rebuild the generic form generator — or replace it with a modern form library driven by the same field metadata.

---

## 14. File-by-file map

### Application core

| Path | Role |
|---|---|
| `iggybase/iggybase.py` | Factory, security, register/new_group, before_request |
| `iggybase/database.py` | Engine, `IggybaseBase`, scoped session, `DBFactory` |
| `iggybase/models.py` | Dynamic lab models |
| `iggybase/tablefactory.py` | Metadata → class |
| `iggybase/cache.py` | In-process cache |
| `iggybase/utilities.py` | `get_table`, filters, dates, `allowed_file` |
| `iggybase/g_helper.py` | `g.rac` / `g.oac` |
| `iggybase/extensions.py` | Mail, LoginManager, Bootstrap |
| `iggybase/base_routes.py` | Home, 403, 404 |

### Engine

| Path | Role |
|---|---|
| `core/role_access_control.py` | Permission plane |
| `core/organization_access_control.py` | Data plane |
| `core/routes.py` | Generic HTTP API of the product |
| `core/table_query*.py` | Saved queries + formatting |
| `core/field*.py` | Field metadata wrappers |
| `core/instance_*.py` | Load/save graph |
| `core/workflow.py`, `work_item_group.py` | Workflow runtime |
| `core/action.py`, `actions.py`, `compare.py` | Hooks |
| `core/calculation.py` | Derived fields |
| `web_files/form_generator.py` | Dynamic WTForms |
| `web_files/form_parser.py` | POST → instances + files |
| `web_files/page_template.py` | Chrome, menus, buttons |
| `web_files/modal_form.py` | Search modal |
| `web_files/iggybase_form_*.py` | Custom WTForms widgets |

### Domain

| Path | Role |
|---|---|
| `admin/models.py` | Metadata + identity schema |
| `admin/routes.py` | Thin admin screens |
| `billing/*` | Invoices, line items, PDFs |
| `murray/routes.py` | Oligo status boards |
| `smallmolecule/lipid_analysis.py` | Lipid CSV pipeline |
| `interfaces/connections.py` | SPINAL session |
| `api/*` | Unused |

### Ops

| Path | Role |
|---|---|
| `scripts/iggy_script.py` | Raw-SQL CLI base |
| `scripts/migrate/*` | Data migrations |
| `scripts/sequencing/*` | Illumina + line items |
| `scripts/murray/*` | Genotype import |
| `scripts/insert/*` | Metadata load |
| `initial_admin.sql` | Seed |
| `apache_conf`, `iggybase.wsgi` | Historical Apache deploy. Not used by Compose |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Current deploy |
| `config.py`, `.env.example` | Environment-backed settings |
| `readme` | How to start Compose and sign in |
| `tests/test_sec_*.py` | Security-slice tests |
| `documents/` | Revival PRD, plans, spec, requirements |

---

## 15. `mod_auth` — the deleted authentication package

`mod_auth` is gone from the tree but still referenced (`lm.login_view = 'mod_auth.login'`, `setup.py`, `initial_admin.sql`). Git still has the full package. It was not Flask-Security. It was the original identity **and** authorization module, in the `mod_*` naming style used by `mod_admin`, `mod_core`, `mod_lab`, `mod_api`, and `mod_murray`.

### 15.1 What it contained

```
iggybase/mod_auth/
  __init__.py          Blueprint('mod_auth', url_prefix='/auth')
  routes.py            login, logout, register, home, getrole, getorganization
  forms.py             LoginForm, RegisterForm
  models.py            User, UserRole, Organization, OrganizationType
  role_access_control.py
  organization_access_control.py
  role_organization.py
  action.py, constants.py, decorators.py
templates/mod_auth/{login,register,failedlogin,regcomplete,regerror}
static/mod_auth/{login.js, main.js}
```

### 15.2 What it did

**Custom Flask-Login, not Flask-Security.** `/auth/login` used a hand-rolled form: username, password, **role**, **organization**, remember-me. Lookup was by `User.name`, then `is_active` + Werkzeug `verify_password`, then `login_user`. Redirect went to `user.home_page` or `?next=`.

**Login chose role and org, not just identity.** After the username field blurred, `login.js` POSTed to `/auth/getrole` and `/auth/getorganization` and filled the dropdowns, defaulting to `current_user_role_id`. Flask-Security cannot do that, which is why role switching later moved into the navbar (`change_role` / `change_user`) after login.

**Registration was a staff-approval queue.** `/auth/register` did not insert a `User`. It inserted a `NewUser` into the admin DB (address, PI, group, institution, hashed password, plus which server/directory you registered against). Copy: “Your registration will be reviewed within 1 business day.” `User.verified` is the collapsed version of that table. The current `/register` + `/new_group` flow in `iggybase.py` is the successor.

**RAC and OAC were born here.** The permission plane started as `mod_auth` files and moved to `core/` when `auth` was deleted. The `User` model started here too (`password_hash`, Flask-Login `UserMixin`, `@lm.user_loader`), then moved to `mod_admin` in January 2016. A `password` column was added next to `password_hash` on 2016-01-13, which is why the current model still has both hash helpers and a `password` field.

### 15.3 Timeline

| When | What happened |
|---|---|
| 2015 | `mod_auth` is login + User/Org models + RAC/OAC |
| Nov 2015 | Login/register templates and JS |
| 2016-01-13 | `password` column added on `User` |
| 2016-01-19 | Model imports pointed at `mod_admin` |
| ~2016-01-25 | `forms.py` deleted; login/register routes leave `mod_auth` |
| Feb 2016 | Flask-Security added (`24a6f79 add flask security`) |
| 2016-02-23 | `mod_` prefix removed → package becomes `auth` |
| 2016-03-10 | `auth/` deleted. Home moves to `base_routes`. Login is Security-only |

Fossils that remain: `setup.py` listing `iggybase.mod_auth`, seed `module` / `page_form` rows for `mod_auth/login` in `initial_admin.sql` (not loaded), `templates/security/*` replacing `templates/mod_auth/*`, and `dupe_roles.py` still importing `iggybase.mod_admin.models`. `lm.login_view` is `security.login` now.

---

## 16. Conclusions

Iggybase is a real LIMS. The person who wrote it understood the domain: cores sell services to labs, labs are trees of people, permissions are a matrix, and the next facility will invent a table you have not heard of yet. The metadata engine, the RAC/OAC split, the workflow bag-of-rows, and the billing module are the artifacts of that understanding.

The 2026 revival kept that engine. The process is Python 3.14, Flask 3.1, SQLAlchemy 2.1, and gunicorn in Compose, published on localhost. The high authorization findings in §8.1–§8.8 have code and MySQL-backed tests. Passwords for new accounts are argon2. The app can serve `/healthz` and `/login` from an empty database.

The scars that were left are specific. §7 still describes defects that would hit invoices, org dropdowns, and bulk update. Script SQL is still interpolated. The request path still prints. `oganization`, the discarded `str.replace`, and `ActionEmail.id == Action.id` still disable the features they sit in. Facility screens do not appear until `table_object` and `field` rows exist. `core` is not a blueprint until a `Module` row says so and the process restarts.

If this is a portfolio piece, the thing to show is the metadata model and the tenancy design, plus the fact that the engine now imports and the high edges are tested.

If this is a system anyone might run beyond this machine, the next work is §7 and the remaining edges in §8 and §12, not another pass over the pins. Do not put `apache_conf` in front of it. Do not publish the Compose port past `127.0.0.1` until those items are closed.

---

*First written against the 2015–2017 tree. Re-reviewed on 2026-10-06 against `master` after the library, security, and Docker slices. `config.py` is in the repo. The Apache vhost was not used. Live facility metadata is still not in git. Grades in §1 are the 2026 grades.*
