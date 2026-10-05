# Plan — Docker deployment

Spec: `documents/spec/docker-deployment.md`
Requirements: `documents/requirements/docker-deployment.md`

Depends on the library plan and the critical-security plan. The image contains those changes.

Do not start the next slice until the current one has been reviewed.

## Slice 1 — Image

DKR-1, DKR-2.

- `Dockerfile` from `python:3.14`, non-root user `iggybase`, gunicorn on port 8000, debugger off.
- Install Cairo, Pango, and a font package.
- `import weasyprint` inside a built image succeeds.

Done when the image builds on this machine.

## Slice 2 — Compose and environment

DKR-3, DKR-4, DKR-5, DKR-8, DKR-9.

- `docker-compose.yml` with `mysql:8` and `web`.
- MySQL healthcheck gates the web process.
- Web port is `127.0.0.1:8000` only. MySQL has no published port.
- Upload volume.
- `.env.example` covers the library configuration table. `.env` is gitignored.
- Do not mount `initial_admin.sql` or `apache_conf`.

Done when `docker compose config` shows those constraints.

## Slice 3 — Health and login

DKR-6, DKR-7.

- Add `GET /healthz` with `SELECT 1`, excluded from the login and facility redirect.
- `docker compose up` reaches a healthy web service.
- `GET /login` returns the login form.
- Open that page in a browser and confirm the form is usable (fields present, no console error from a missing script on that page).

Done when the browser check and the healthcheck both pass. Empty facility screens are expected.

## Slice 4 — PDF smoke

DKR-10.

Run the WeasyPrint one-liner from the spec inside `web`. The bytes start with `%PDF`.

Done when that command prints those bytes.

## Out of scope

TLS, a production dump, loading `initial_admin.sql`, and running the sequencing or migrate scripts inside the container.
