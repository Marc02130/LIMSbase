# Requirements — Docker deployment

Depends on the library and critical-security requirements. The image is built from that tree.

| ID | Requirement |
|---|---|
| DKR-1 | `Dockerfile` uses a Python 3.14 base image. The process runs as a non-root user. The server is gunicorn. The Werkzeug debugger is not enabled. |
| DKR-2 | The image includes Cairo and Pango so WeasyPrint can render. `import weasyprint` succeeds inside the container. |
| DKR-3 | `docker-compose.yml` defines `web` and `mysql` (MySQL 8). The web process starts only after MySQL is healthy. |
| DKR-4 | The published web port binds to `127.0.0.1` only. MySQL is not published on a public interface. |
| DKR-5 | `.env.example` lists every variable `config.py` reads, with placeholders. It contains no real secret. `.env` is gitignored if a local file is used. |
| DKR-6 | `GET /healthz` does not require a login. It returns HTTP 200 only when the process can run a trivial query against MySQL. |
| DKR-7 | On an empty data database, startup runs `create_all` for the admin models. `GET /login` returns the login form. |
| DKR-8 | `initial_admin.sql` is not mounted as a MySQL init script. `apache_conf` is not copied into the image as the server config. |
| DKR-9 | Uploads are stored on a volume mounted at `UPLOAD_FOLDER` / `FILE_FOLDER`, not only in the container filesystem. |
| DKR-10 | A one-page HTML string rendered with WeasyPrint inside the container produces a PDF byte string whose header is `%PDF`. |

Facility summary screens that need metadata rows are not required to render. Empty metadata is the expected boot state.
