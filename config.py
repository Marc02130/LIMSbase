import os
from urllib.parse import quote


class MissingConfig(RuntimeError):
    """Raised when a required environment variable is missing or blank."""


def _required(name):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise MissingConfig("Missing required environment variable: %s" % name)
    return value


def _optional(name, default=None):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _database_uri():
    explicit = _optional("SQLALCHEMY_DATABASE_URI")
    if explicit:
        uri = explicit
    else:
        user = quote(_required("DB_USER"), safe="")
        password = quote(_required("DB_PASSWORD"), safe="")
        host = _required("DB_HOST")
        port = _optional("DB_PORT", "3306")
        uri = "mysql+pymysql://%s:%s@%s:%s/" % (user, password, host, port)
    if not uri.endswith("/"):
        uri += "/"
    return uri


def _extension_set(value):
    return {part.strip() for part in value.split(",") if part.strip()}


class Config:
    SECRET_KEY = _required("SECRET_KEY")
    SECURITY_PASSWORD_SALT = _required("SECURITY_PASSWORD_SALT")
    SECURITY_PASSWORD_HASH = _optional("SECURITY_PASSWORD_HASH", "argon2")

    # Browsers send cookies to every port on a host. The default name "session"
    # collides with other local apps, and a login POST then has no CSRF token.
    SESSION_COOKIE_NAME = "iggybase_session"
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_NAME = "iggybase_remember"

    DB_USER = _required("DB_USER")
    DB_PASSWORD = _required("DB_PASSWORD")
    DB_HOST = _required("DB_HOST")
    DB_PORT = _optional("DB_PORT", "3306")
    DATA_DB_NAME = _required("DATA_DB_NAME")
    SEMANTIC_DB_NAME = _optional("SEMANTIC_DB_NAME")
    SQLALCHEMY_DATABASE_URI = _database_uri()

    UPLOAD_FOLDER = _required("UPLOAD_FOLDER")
    FILE_FOLDER = _required("FILE_FOLDER")
    ALLOWED_EXTENSIONS = _extension_set(_required("ALLOWED_EXTENSIONS"))

    SPINAL_DATABASE_URI = _optional("SPINAL_DATABASE_URI")
    SPINAL_DB_NAME = _optional("SPINAL_DB_NAME")


_mail_server = _optional("MAIL_SERVER")
if _mail_server:
    Config.MAIL_SERVER = _mail_server
    Config.MAIL_PORT = int(_optional("MAIL_PORT", "25"))
    Config.MAIL_USE_TLS = _as_bool(_optional("MAIL_USE_TLS", ""))
    _mail_username = _optional("MAIL_USERNAME")
    if _mail_username:
        Config.MAIL_USERNAME = _mail_username
    _mail_password = _optional("MAIL_PASSWORD")
    if _mail_password:
        Config.MAIL_PASSWORD = _mail_password
    _mail_sender = _optional("MAIL_DEFAULT_SENDER")
    if _mail_sender:
        Config.MAIL_DEFAULT_SENDER = _mail_sender
