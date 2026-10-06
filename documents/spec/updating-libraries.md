# Spec — updating libraries

Meets `documents/requirements/updating-libraries.md`. No authorization behavior changes (LIB-13).

## Package set

Replace `requirements.txt` with direct dependencies only. Pin each package, at implementation time, to the current stable release that declares Python 3.14 support. Do not invent pins in advance of that check.

| Need | Package | Import |
|---|---|---|
| Web framework | Flask 3.1 line | `flask` |
| Matching server utilities | The Werkzeug, Jinja2, ItsDangerous, and MarkupSafe releases Flask 3.1 requires | |
| ORM | SQLAlchemy 2.x | `sqlalchemy` |
| Legacy query helper used by `Base.query` | Kept: `scoped_session.query_property()` | |
| MySQL driver | PyMySQL | URL scheme `mysql+pymysql` |
| Login, mail | Flask-Login, Flask-Mail | `flask_login`, `flask_mail` |
| Forms | Flask-WTF, WTForms, WTForms-SQLAlchemy | `flask_wtf`, `wtforms`, `wtforms_sqlalchemy` |
| Identity | Flask-Security-Too | `flask_security` |
| Password hash | The hasher Flask-Security-Too selects (`argon2-cffi` or `bcrypt`) | |
| Spreadsheets | Flask-Excel and the pyexcel stack it currently requires | `flask_excel` |
| Images and PDF | Pillow, WeasyPrint, Flask-WeasyPrint | `PIL`, `weasyprint`, `flask_weasyprint` |
| Process | gunicorn | Used by the Docker plan |
| Cache | cachelib (`werkzeug.contrib.cache` is gone) | `cachelib` |
| App imports | numpy, python-dateutil, email-validator | |
| Password hashing library | libpass, pulled in by Flask-Security-Too 5.9 | |

Remove from the pin file: `mod-wsgi`, `virtualenv`, `virtualenvwrapper`, `ipython`, `BareNecessities`, `pbr`, `stevedore`, `mysql-connector-python-rf`, and other packages that were only present because `pip freeze` captured a workstation. Do not revive `setup.py`.

If a named package has no 3.14 wheel and is not pure Python, replace it in this slice and record the replacement here. Do not drop the interpreter version.

## Import map

| Current | Replacement |
|---|---|
| `flask.ext.security` | `flask_security` |
| `flask.ext.security.registerable.register_user` | `flask_security.registerable.register_user` |
| `flask.ext.mail` | `flask_mail` |
| `flask.ext.login` | `flask_login` |
| `flask.ext.wtf.Form` and `flask_wtf.Form` | `flask_wtf.FlaskForm` |
| `flask.ext.excel` | `flask_excel` |
| `wtforms.ext.sqlalchemy.orm.model_form`, `QuerySelectField` | `wtforms_sqlalchemy.orm.model_form`, `wtforms_sqlalchemy.fields.QuerySelectField` |

Files that import these today: `iggybase/iggybase.py`, `extensions.py`, `admin/models.py`, `admin/routes.py`, `core/routes.py`, `core/action.py`, `billing/routes.py`, `murray/routes.py`, `smallmolecule/routes.py`, `smallmolecule/lipid_analysis.py`, `interfaces/routes.py`, `web_files/forms.py`, `web_files/form_generator.py`.

`lm.login_view = 'mod_auth.login'` points at a module that is not in the tree. Login is Flask-Security's `/login`. Point `login_view` at `security.login`.

## Configuration

Add `config.py` at the repository root so `from config import Config` keeps working. `Config` reads the environment. Missing required variables raise at process start with the variable name.

`database.py` builds the URL by concatenation:

```text
SQLALCHEMY_DATABASE_URI + DATA_DB_NAME
```

`SQLALCHEMY_DATABASE_URI` therefore ends with `/`, for example `mysql+pymysql://USER:PASSWORD@HOST:PORT/`. `DATA_DB_NAME` is the schema name only.

| Variable | Required | Maps to |
|---|---|---|
| `SECRET_KEY` | yes | `SECRET_KEY` |
| `SECURITY_PASSWORD_SALT` | yes | `SECURITY_PASSWORD_SALT` |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST` | yes | same attribute names, for the scripts |
| `DB_PORT` | no, default `3306` | used to build the URI |
| `DATA_DB_NAME` | yes | `DATA_DB_NAME` |
| `SEMANTIC_DB_NAME` | no | `SEMANTIC_DB_NAME`, scripts only |
| `SQLALCHEMY_DATABASE_URI` | derived if unset | `mysql+pymysql://…/` from the DB_* pieces |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_DEFAULT_SENDER` | no | Flask-Mail. Unset mail does not block import |
| `UPLOAD_FOLDER`, `FILE_FOLDER` | yes | same config keys |
| `ALLOWED_EXTENSIONS` | yes | comma-separated list, stored as a set |
| `SPINAL_DATABASE_URI`, `SPINAL_DB_NAME` | no | Read by `interfaces/connections.py` only when that module opens a connection |

Do not commit a filled `.env`. The Docker plan adds `.env.example`.

`interfaces/connections.py` opens an engine at import. LIB-7 requires that importing the web app does not do that. Move the engine creation behind the first use of the SPINAL connection, and tolerate an unset URI until that call.

## Identity model

Stay on the custom engine. Do not add Flask-SQLAlchemy as the application database.

`DBFactory` already exposes `.session`. Confirm Flask-Security-Too's `SQLAlchemyUserDatastore(db, User, Role)` uses that session. Keep `Base.query = db_session.query_property()`. Do not rewrite queries to `select()`.

The first database is empty, and the first account is a new admin user. This plan does not preserve legacy Werkzeug or passlib password hashes.

On `User` in `iggybase/admin/models.py`:

- `password = Column(String(255))`
- `fs_uniquifier = Column(String(64), unique=True, nullable=False)`
- Keep `verified`
- Keep `is_active` as `self.active and self.verified`

Empty-database `create_all` supplies the new column. A later import of a real dump must backfill `fs_uniquifier` before anyone logs in. That backfill is not part of this plan.

`ExtendedLoginForm` and `ExtendedRegisterForm` stay subclasses of the Flask-Security-Too forms. Adjust only what the new class signatures require so the existing fields still register. Do not redesign registration.

Set `SECURITY_PASSWORD_HASH` to the hasher installed above. Flask-Security-Too rehashes a legacy hash on successful login when this is configured. Verifying a real legacy hash needs a row from an old database and belongs with the dump import, not this plan.

## Bootstrap

Templates call `bootstrap_find_resource` and import `bootstrap/wtf.html`, and `data_entry.html` calls `bootstrap_is_hidden_field`. Flask-Bootstrap 3.3 does not run on Flask 3.

Preferred approach: a small helper registered in `create_app` that provides those Jinja globals and a `bootstrap/wtf.html` equivalent for Bootstrap 3. Keep the Bootstrap 3 class names. Do not move the UI to Bootstrap 5.

If matching `wtf.quick_form` / `wtf.form_errors` takes more code than switching the template imports to Bootstrap-Flask, switch and list the templates edited. No visual redesign either way.

## PDF libraries

Pillow must import after install (LIB-12).

WeasyPrint imports only when Cairo and Pango are present. The library slice records whether the developer machine can import it. The Docker image is the environment that must import it (DKR-2). This plan does not render an invoice.

Checked 2026-10-05 in the Python 3.14 environment that installed `requirements.txt`. `import PIL` (Pillow 12.3.0), `import weasyprint` (70.0), and `from flask_weasyprint import HTML, render_pdf` (Flask-WeasyPrint 1.2.0) all succeed. `pkg-config` reports Cairo 1.18.4, Pango 1.57.0, and GDK-Pixbuf 2.44.5. No PDF was rendered here. The container render check remains DKR-10.

## Boot check

`database.py` creates the engine at import, and `iggybase/models.py` runs `TableFactory` at import. LIB-10 is:

1. MySQL is up and `DATA_DB_NAME` exists.
2. Environment variables from the table above are set.
3. `import iggybase` returns.
4. Admin tables from `admin/models.py` exist after `init_db()`.

An empty `table_object` set means no dynamic lab classes. That is a successful import.

## Explicitly unchanged

Route decorators, org filters, CSRF, cache rules, and action import policy. Those are the security plan.
