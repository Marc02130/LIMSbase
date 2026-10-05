from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, DateField, TextAreaField, FloatField, SelectField,\
    FileField, PasswordField, DecimalField
from wtforms.validators import DataRequired, Length, email, Optional

class CacheForm(FlaskForm):
    key = StringField('Key')
    value = StringField('Value')
    refresh_obj = StringField('Refresh Object')
    version = StringField('Version')
