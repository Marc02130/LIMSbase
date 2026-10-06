# Spec — Docker deployment

Meets `documents/requirements/docker-deployment.md`. Built only after the library and security plans are in the tree. `apache_conf` stays in the repository as history and is not the image entrypoint.

## Image

`Dockerfile` from `python:3.14`. Install Cairo, Pango, GDK-Pixbuf, and shared-mime-info so WeasyPrint imports (DKR-2), plus a font package so a smoke PDF has glyphs.

Create a user and group named `iggybase` with a non-zero uid. `USER iggybase` before the server starts. Application code is owned by that user. Do not run gunicorn as root.

Install from `requirements.txt`. Do not copy a virtualenv from the host.

Entrypoint runs gunicorn bound to `0.0.0.0:8000`, calling the app object `iggybase` created in `run.py`. Workers: 2. No `--reload` in the default command. `FLASK_DEBUG` and `DEBUG` are unset. `run.py` must not call `app.run(debug=True)`.

`EXPOSE 8000` is documentation. Compose publishes it.

## Compose

Services:

| Service | Image | Role |
|---|---|---|
| `mysql` | `mysql:8` | Data store. Database name matches `DATA_DB_NAME`. |
| `web` | the Dockerfile | gunicorn |

`mysql` has a healthcheck of `mysqladmin ping`. `web` uses `depends_on` with `condition: service_healthy`.

`web` publishes `127.0.0.1:18000:8000` only. Host port 8000 is already taken on this machine. `mysql` has no `ports:` entry. The web container reaches it on the Compose network as host `mysql`.

Named volumes:

- `mysql-data` on the MySQL data directory
- `uploads` mounted at both `UPLOAD_FOLDER` and `FILE_FOLDER` when those paths differ; one mount is enough when the configuration points them at the same directory

No bind-mount of the source tree is required for the acceptance run. A bind mount may be added later for development and is not part of DKR-7.

## Environment

`.env.example` lists every variable in the library spec's configuration table, plus:

| Variable | Example |
|---|---|
| `MYSQL_DATABASE` | same value as `DATA_DB_NAME` |
| `MYSQL_USER` / `MYSQL_PASSWORD` | same as `DB_USER` / `DB_PASSWORD` |
| `MYSQL_ROOT_PASSWORD` | placeholder |

`DB_HOST` inside Compose is `mysql`. `SQLALCHEMY_DATABASE_URI` is `mysql+pymysql://…@mysql:3306/`.

`.gitignore` includes `.env` if it does not already. The example file uses placeholders such as `change-me`, not a generated secret that looks real.

## Health

Add `GET /healthz` on the app, not under a facility prefix, and not decorated with `@login_required`. `before_request` must not redirect it to login or require a facility.

The handler runs `SELECT 1` on the application engine. Success returns `200` and `{"status": "ok"}`. A database error returns `503`.

Compose healthcheck for `web` requests `http://127.0.0.1:8000/healthz`.

## Empty database

`init_db()` already calls `create_all`. On a new volume that creates the admin tables from `iggybase/admin/models.py`, including `fs_uniquifier` and the widened password column.

Do not copy `initial_admin.sql` into `/docker-entrypoint-initdb.d`. Module names in that dump (`mod_auth`, `mod_lab`, `mod_admin`) do not match the blueprint packages.

With no `module` rows where `blueprint = 1`, no facility blueprints are registered. Flask-Security-Too still serves `/login`. DKR-7 is that page's HTML, not a facility home screen.

## PDF smoke

Not a route. A documented command:

```text
docker compose exec web python -c "from weasyprint import HTML; print(HTML(string='<p>iggybase</p>').write_pdf()[:5])"
```

The first five bytes print as `%PDF` (DKR-10). This proves the system libraries. It does not require invoice metadata.

## What the container does not do

- TLS termination. Binding to localhost is the stand-in until a reverse proxy exists.
- Load a production dump.
- Run the Illumina, Murray, or migrate scripts. Those stay operator commands against the same database variables.
