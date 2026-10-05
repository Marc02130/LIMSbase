from flask_mail import Mail
mail = Mail( )

from flask_login import LoginManager
lm = LoginManager( )
lm.session_protection = 'strong'
lm.login_view = 'security.login'


class Bootstrap:
    # Slice 4 registers the Bootstrap 3 template helpers.
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        return None


bootstrap = Bootstrap( )
