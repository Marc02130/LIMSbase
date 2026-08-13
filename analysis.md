# Iggybase LIMS — Codebase Analysis

**Repository:** LIMSbase (`iggybase`)
**First commit:** 2015-07-09
**Last development era:** ~2015–2017 (Python 3.4 / Flask 0.12)
**Size:** ~13,200 lines of application Python across ~100 modules; 1,200+ commits
**Runtime:** Flask + SQLAlchemy + MySQL, Apache `mod_wsgi`, Harvard FAS core facilities

This document is a thorough architectural, security, and maintainability review of the existing codebase. It is written as a record of what the system is, what is valuable in it, what is dangerous, and what it would take to revive or replace it.

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

That design is still how a configurable LIMS should work. The implementation around it is a 2015 academic-core Flask app: end-of-life dependencies, no automated tests, several authorization holes, leftover debug prints, and a number of production-grade bugs that were never closed.

**The short version:** keep the metadata model, the access-control idea, the workflow engine, and the billing rules. Do not put this stack on a network as-is. Do not throw the domain model away and start from a blank Django app.

| Area | Grade | Notes |
|---|---|---|
| Domain model | Strong | Table/field/role/org/workflow is the hard part, and it is here |
| Access-control *idea* | Strong | Facility × role × org tree is the right LIMS tenancy model |
| Access-control *enforcement* | Weak | Several routes skip org filters; impersonation exists |
| Generic CRUD engine | Strong concept, fragile code | Form generator/parser and table queries are ambitious |
| Billing | Strong | Real invoicing, not a script |
| Security | Fail | Unauthenticated search, XSS, file leak, EOL stack, CSRF gaps |
| Test coverage | None | No pytest/unittest suite |
| Operability | Dated | In-process cache, Apache 2.2 authz, HTTP-only vhost |
| Revive-in-place cost | High | Python 3.4 / Flask 0.12 / Flask-Security 1.7 |

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

### 3.1 Stack as frozen in `requirements.txt`

```
Python          3.4.1          (EOL 2019-03-18)
Flask           0.12.1         (known CVEs; long superseded)
Jinja2          2.9.6
Werkzeug        0.12.1
Flask-SQLAlchemy 2.0
SQLAlchemy      1.1.9
Flask-Security  1.7.5
Flask-Login     0.3.2
Flask-WTF       0.12
WTForms         2.0.2
mysql-connector-python-rf 2.0.4
WeasyPrint      0.36
Flask-WeasyPrint 0.5
Pillow          4.0.0
mod-wsgi        4.4.22
```

`readme` is an ops runbook for building CPython 3.4.1 from source on RHEL/CentOS (`yum groupinstall "Development tools"`), compiling `mod_wsgi` 4.4.12 against a venv at `/n/informatics/iggybase/iggybase_env`, and installing into that venv.

`iggybase.wsgi` activates that venv, inserts the app onto `sys.path`, and logs to `iggybase.log`. `run.py` is a thin `create_app()` wrapper for the Flask dev server.

`config` is imported from **outside the repository** (`from config import Config`). Database URI, mail, upload folder, secret key, and `ADMINS` live in an untracked module. That was a reasonable 2015 secrets practice; it also means a fresh clone cannot start.

### 3.2 Deployment

`apache_conf` is a single HTTP vhost:

- `WSGIScriptAlias /` → `iggybase.wsgi`
- `WSGIDaemonProcess` with `threads=15`
- `Options Indexes FollowSymLinks MultiViews`
- Apache 2.2 authorization (`Order allow,deny` / `Allow from all`)
- no TLS in the checked-in config
- error log next to the application code

`setup.py` is not a real package definition. It was generated from a live virtualenv and lists hundreds of `iggybase_env.lib.python3.4.site-packages.*` packages, including pip internals and Flask’s own test apps. It should not be used and should not be in git.

### 3.3 What is *not* in the repo

- `config.py` / secrets
- tests
- CI
- a Dockerfile or compose file
- a migrations framework (Alembic is not used; schema evolution is SQL scripts)
- the live metadata that defines most tables (only `initial_admin.sql` is checked in)
- an API implementation (`iggybase/api/` is a scaffold)

The application cannot be understood from models.py alone. The real schema is the contents of `table_object` and `field` in a running database.

---

## 4. Architecture

### 4.1 Top-level layout

```
LIMSbase/
  run.py, iggybase.wsgi, setup.py, requirements.txt, readme
  apache_conf
  initial_admin.sql          # seed metadata + admin schema
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

1. Load `Config`
2. Attach `Cache()` to the app
3. `init_db()` — import `iggybase.models` (which runs TableFactory) and `create_all`
4. Register blueprints from the `module` table
5. Init Bootstrap, LoginManager, Mail, Flask-Security
6. Register base routes (register, new_group, welcome, index, home)
7. Install `before_request` / `after_request` / error handlers

This is a classic Flask 0.12 factory. Two things make it unusual:

- **Boot requires a live MySQL** with metadata already loaded. `models.py` queries `table_object` at import time. An empty database, a down database, or a metadata mismatch prevents the process from starting.
- **Blueprints are data.** Adding a module is an insert into `module` plus a Python package, not a code change in `create_app`.

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

A LIMS holds identified research data, user PII (names, emails, addresses, phones), and billing instruments (Harvard 33-digit codes, charge methods). The bar is not “internal tool.” Several findings would fail a basic application-security review.

### 8.1 Unauthenticated search — high

```python
@core.route('/search', methods=['GET', 'POST'])
def search(facility_name):
    ...
@core.route('/search_results', methods=['GET', 'POST'])
def search_results(facility_name):
```

No `@login_required`. `before_request` does not construct RAC/OAC for anonymous users. `ModalForm` then runs whatever lookup `search_vals` describes.

### 8.2 Generic row fetch with org filter off — high

```python
@core.route('/get_row/<table_name>/ajax')
def get_row(...):
    row = oac.get_row(table_name, criteria)  # org_filter=False
```

Any authenticated user who can reach `core.get_row` can read arbitrary columns from any table `get_table` will resolve, by any equality criteria the client sends. That includes admin tables if they are registered as `admin_table`.

### 8.3 Impersonation / org-scope switch — high

`POST /core/change_user` with `{user_id}`:

1. Requires only that the target user shares a facility role with the caller
2. Does not re-bind Flask-Login
3. Recomputes `org_ids` as the target user

A facility admin (or anyone granted the route — it is metadata) can browse another PI’s entire org tree. There is no audit log, time box, or banner.

`make_user_menu` exposes the full user list in the chrome.

### 8.4 File download is not org-checked — high

```python
@core.route('/files/<table_name>/<row_name>/<filename>')
def file_row(...):
    return send_from_directory(FILE_FOLDER / table_name / row_name, filename)
```

Authorization is “logged in.” `send_from_directory` prevents `../` escape, but any authenticated user who can guess or enumerate `table/row/filename` gets the file. Charge-method PDFs and CSVs are already in the git tree under `files/`.

### 8.5 Stored XSS in summaries — high

```python
col = ('<a href="' + link + col + '">' + col + '</a>')
```

This is assembled in SQL and returned as DataTables JSON. Sample names, oligo names, descriptions — anything a user can type into a linked field — become HTML. A lab user can attack a facility admin who opens a summary.

Fix: return a structured `{text, href}` and let the client or Jinja escape.

### 8.6 CSRF gaps — medium / high

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

`/core/cache/` is a logged-in form that gets and sets arbitrary cache keys and version numbers. It is not role-restricted in code (only via `route_role` metadata). Combined with the summary cache, an attacker can plant a JSON payload that a summary page will serve to other users (XSS amplifier) or force versions that resurrect stale data.

### 8.8 Dynamic import from the database — high if admin is compromised

`Action.namespace` + `Action.function` are `import_module`’d and called. Anyone who can edit `action` (or SQL-inject into it via a script) has RCE in the web worker.

Mitigation if the engine is kept: allowlist `(module, function)` pairs in code.

### 8.9 End-of-life dependencies — high

Python 3.4, Flask 0.12, Jinja2 2.9, Werkzeug 0.12, Pillow 4, WeasyPrint 0.36, html5lib 0.999999999. Public CVEs exist across this set (Flask/Jinja XSS and sandbox issues, Pillow image bombs, old Werkzeug debugger risks). Even a “private” core-facility server on the Harvard network is a poor place for this combination in 2026.

### 8.10 Transport and Apache config — medium

Checked-in vhost is HTTP, directory indexes on, `Allow from all`, `FollowSymLinks`, logs and the WSGI file inside the document root pattern (`/var/www/html/iggybase`). `Options Indexes` on a LIMS is how `files/` and `iggybase.log` get listed.

### 8.11 Scripts use string-built SQL — medium (ops path)

`IggyScript.pk_exists` and the migrate/Illumina scripts interpolate identifiers and values. These run with DB credentials from `Config`. A hostile filename or RunInfo field is a plausible injection if a script is pointed at untrusted input.

### 8.12 Password and session notes

- `lm.session_protection = 'strong'` is good.
- Secret key is in external `Config` — fine, as long as it was not reused and is long enough.
- Flask-Security 1.7 password hashing / token salts should be treated as legacy. On revival, re-hash on login.
- `User.password` is 120 chars; some modern hashes are longer.

### 8.13 Information disclosure

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

The engine *wanted* to be careful. Enforcement is incomplete at the edges: search, get_row, files, change_user, cache, bulk update, modal submit.

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

**No tests.** A metadata engine, an org-tree walk, a form parser, and invoice totals with no unit or integration tests means every change is a production experiment.

**Debug left in the request path.** `print('before_request:…')`, `print('oac init:…')`, `print('cache miss')`, `print('rollback')`, `print('extra')` during the org walk.

**Bare `except:`** in save/insert/SPINAL/get_func. Failures become a log line and `None`.

**Inconsistent style.** Spaces inside parentheses (`create_app( )`), mixed `filter_by` / `filter`, mixed Python 2 comments (`#python3`, `#if isinstance(pk, basestring)`), leftover `flask.ext.*` imports (removed in Flask 1.0; the project already uses a mix of `flask.ext.security` and `flask_weasyprint`).

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

- `readme` — Python 3.4 + mod_wsgi install only
- Inline comments and TODOs — the best docs in the repo
- No architecture doc, no ERD, no operator runbook, no data dictionary beyond `initial_admin.sql`

This file is intended to close that gap.

---

## 10. Data and operations

### 10.1 Database

Single MySQL database (`Config.SQLALCHEMY_DATABASE_URI + Config.DATA_DB_NAME`). Admin metadata and lab data share an engine and a session. Comments in `database.py` mention mimicking Flask-SQLAlchemy for Flask-Security (`DBFactory`); there is no second “admin DB” at runtime despite comments that talk about one.

`pool_recycle=3600` is the standard MySQL wait_timeout dodge.

`init_db()` calls `create_all`. That will create missing tables from current models; it will not migrate columns. Schema evolution is `scripts/migrate/*` and hand SQL.

### 10.2 Files

Uploads go to `Config.UPLOAD_FOLDER / <table> / <row_name> / <filename>`. The repo also contains `files/charge_method/CM000000/` with a real PDF, CSV, and workflow PNG. Those look like production fixtures that should not live in git (PII / contractual documents risk).

### 10.3 Logging

`logging.basicConfig` to `iggybase.log` at DEBUG, configured both in `create_app` and in the WSGI file. `sys.path` is also given a directory named `iggybase.log`, which is accidental.

No request id, no structured logs, no access/authorization audit trail for `change_user`, role change, invoice generate, or bulk update.

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

1. **The runtime.** Python 3.4, Flask 0.12, Flask-Security 1.7, `flask.ext.*`, Werkzeug 0.12, Pillow 4, WeasyPrint 0.36.

2. **Boot-time TableFactory against a live DB.** Generate models offline, or load a registry after a health-checked DB connection with an explicit refresh endpoint. The app must start far enough to say “database unavailable.”

3. **In-process `SimpleCache` and the `/cache/` UI.** Use Redis if summaries are actually hot; otherwise delete until measured.

4. **HTML-in-SQL links.**

5. **`setup.py` as venv dump, DataTables examples, datepicker locale forest.**

6. **`change_user` as currently designed.** If support needs impersonation, do it as a time-boxed, audited, clearly-bannered session, not an org_id swap.

7. **Public search, default-off org filters, login-only file server.**

8. **Action `import_module` from arbitrary namespace.** Allowlist.

9. **Apache 2.2 HTTP vhost with Indexes.**

10. **Hardcoded FAS letterhead in invoice.py** — move to `facility` / config.

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

### Option C — In-place upgrade (not recommended)

A Flask 0.12 → 3.x + Python 3.4 → 3.12 upgrade across `flask.ext`, WTForms 2, Flask-Security 1.7, and dynamic model generation is a rewrite with extra steps. You would still need to fix every item in §7 and §8.

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
| `apache_conf`, `iggybase.wsgi`, `readme` | Deploy |

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

Fossils: `lm.login_view`, `setup.py` listing `iggybase.mod_auth`, seed `module` / `page_form` rows for `mod_auth/login` etc., `templates/security/*` replacing `templates/mod_auth/*`, and `dupe_roles.py` still importing `iggybase.mod_admin.models`.

---

## 16. Conclusions

Iggybase is a real LIMS. The person who wrote it understood the domain: cores sell services to labs, labs are trees of people, permissions are a matrix, and the next facility will invent a table you have not heard of yet. The metadata engine, the RAC/OAC split, the workflow bag-of-rows, and the billing module are the artifacts of that understanding.

The implementation is a 2015 Flask app that grew until it invoiced PIs. It has the expected scars: no tests, EOL libraries, debug prints, a few inverted booleans, a few typos that disable whole features (`oganization`, discarded `str.replace`, `ActionEmail.id == Action.id`), and authorization that is strong in the center and porous at the edges.

If this is a portfolio piece, the thing to show is the metadata model and the tenancy design, not the Flask 0.12 handlers.

If this is a system anyone might run again, the metadata tables and the billing rules are the migration source. The process that currently interprets them should not be put back on a network without the work in §8 and §13.

---

*Analysis based on the repository as of the date of this document. Live database contents, the external `config` module, and production Apache/TLS settings were not available and may differ from what is checked in.*
