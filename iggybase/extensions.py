from flask import current_app
from flask_mail import Mail
from wtforms.fields import HiddenField
mail = Mail( )

from flask_login import LoginManager
lm = LoginManager( )
lm.session_protection = 'strong'
lm.login_view = 'security.login'


# Flask-Bootstrap 3.3.7 CDN locations. Minified names match that package:
# css/bootstrap.css -> css/bootstrap.min.css, jquery.js -> jquery.min.js.
_BOOTSTRAP_VERSION = "3.3.7"
_JQUERY_VERSION = "1.12.4"
_CDN_BASES = {
    "bootstrap": "//cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/%s/"
                 % _BOOTSTRAP_VERSION,
    "jquery": "//cdnjs.cloudflare.com/ajax/libs/jquery/%s/" % _JQUERY_VERSION,
    "html5shiv": "//cdnjs.cloudflare.com/ajax/libs/html5shiv/3.7.3/",
    "respond.js": "//cdnjs.cloudflare.com/ajax/libs/respond.js/1.4.2/",
}


def bootstrap_is_hidden_field(field):
    return isinstance(field, HiddenField)


def bootstrap_find_resource(filename, cdn, use_minified=None, local=True):
    """Return the Bootstrap 3 CDN URL for a template resource call."""
    config = current_app.config
    if use_minified is None:
        use_minified = config.get("BOOTSTRAP_USE_MINIFIED", True)
    if use_minified:
        stem, ext = filename.rsplit(".", 1)
        filename = "%s.min.%s" % (stem, ext)
    url = _CDN_BASES[cdn] + filename
    if url.startswith("//") and config.get("BOOTSTRAP_CDN_FORCE_SSL"):
        url = "https:" + url
    return url


class Bootstrap:
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.config.setdefault("BOOTSTRAP_USE_MINIFIED", True)
        app.config.setdefault("BOOTSTRAP_CDN_FORCE_SSL", False)
        app.add_template_global(
            bootstrap_is_hidden_field, name="bootstrap_is_hidden_field")
        app.add_template_global(
            bootstrap_find_resource, name="bootstrap_find_resource")


bootstrap = Bootstrap( )
