# Requirements — updating libraries

Each item is pass or fail. This plan does not change who may call a route.

| ID | Requirement |
|---|---|
| LIB-1 | On Python 3.14, `pip install -r requirements.txt` completes. Every installed distribution publishes a 3.14 wheel or is pure Python. |
| LIB-2 | The pin set no longer includes `mod-wsgi`, `virtualenv`, `virtualenvwrapper`, `ipython`, `BareNecessities`, `pbr`, `stevedore`, or `mysql-connector-python-rf`. |
| LIB-3 | No application module imports `flask.ext`. |
| LIB-4 | Forms subclass `flask_wtf.FlaskForm`. `model_form` and `QuerySelectField` come from WTForms-SQLAlchemy. |
| LIB-5 | `config.py` in the repository reads the environment. It is imported as `config.Config`. No secret value is committed. |
| LIB-6 | `SQLALCHEMY_DATABASE_URI + DATA_DB_NAME` still forms the URL `database.py` passes to `create_engine`. The driver is PyMySQL. |
| LIB-7 | `SPINAL_DATABASE_URI` may be unset. Importing the web application does not open a SPINAL connection unless that code path runs. |
| LIB-8 | `User.password` is a string of length 255. `User.fs_uniquifier` exists, is unique, and is non-null. The `verified` column remains. `User.is_active` is true only when `active` and `verified` are both true. |
| LIB-9 | Flask-Security-Too is the identity package (`flask-security-too`, imported as `flask_security`). `DBFactory.session` is the session the datastore uses. Queries stay on `session.query()`. |
| LIB-10 | With MySQL reachable and the environment set, `import iggybase` succeeds and `create_all` builds the admin tables on an empty database. |
| LIB-11 | Login and registration templates still resolve `bootstrap_find_resource` and `bootstrap/wtf.html`. Bootstrap 3 markup is unchanged. |
| LIB-12 | Pillow imports on Python 3.14. WeasyPrint imports on Python 3.14 where Cairo and Pango are installed. |
| LIB-13 | This plan does not add or remove `@login_required`, org filters, or CSRF checks. |

Deferred to the Docker plan: system libraries for WeasyPrint, gunicorn as the process manager, and rendering a PDF.
