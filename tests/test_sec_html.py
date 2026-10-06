"""MySQL-backed checks for stored HTML in summary and save links (SEC-11).

Uses iggybase_sec6 so the other security schemas stay untouched. MySQL root
recreates the schema. The application user then owns it.

sample_note is a dynamic table. Its metadata is inserted before create_app,
which is what imports iggybase.models and builds the class.
"""
import json
import os
import sys
import unittest
import uuid

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SECURITY_PASSWORD_SALT", "test-salt")
os.environ.setdefault("DB_USER", "iggybase")
os.environ.setdefault("DB_PASSWORD", "change-me")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ["DATA_DB_NAME"] = "iggybase_sec6"
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/iggybase-uploads")
os.environ.setdefault("FILE_FOLDER", "/tmp/iggybase-sec6-files")
os.environ.setdefault("ALLOWED_EXTENSIONS", "pdf,csv,txt")

import pymysql

_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "change-me")
_conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    user="root",
    password=_ROOT_PASSWORD,
)
try:
    with _conn.cursor() as _cur:
        _cur.execute("DROP DATABASE IF EXISTS iggybase_sec6")
        _cur.execute(
            "CREATE DATABASE iggybase_sec6 CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci"
        )
        _cur.execute(
            "GRANT ALL PRIVILEGES ON iggybase_sec6.* TO 'iggybase'@'%'"
        )
        _cur.execute("FLUSH PRIVILEGES")
    _conn.commit()
finally:
    _conn.close()

from flask_security.utils import hash_password
from iggybase import create_app
from iggybase.admin import models
from iggybase.database import Base, db_session, engine

PASSWORD = "html-secret"
EMAIL = "html@example.com"
TABLE = "sample_note"
# Factory uses id 6 for the file column. Id 2 is the string type and is not
# added again because name is a predefined column.
STRING_TYPE_ID = 2
FILE_TYPE_ID = 6
STORED = "<script>"
FILE_NAME = "<script>.txt"


def _add(model, **kwargs):
    row = model()
    for key, value in kwargs.items():
        setattr(row, key, value)
    db_session.add(row)
    return row


def _seed_before_models():
    """Admin rows the dynamic table factory reads at import time."""
    if "iggybase.models" in sys.modules:
        raise AssertionError("iggybase.models was imported before sample_note existed")
    Base.metadata.create_all(bind=engine)

    root = _add(models.Organization, name="facility-root", active=True)
    everyone = _add(models.Organization, name="Everyone", active=True)
    outsider = _add(models.Organization, name="outsider-org", active=True)
    db_session.flush()
    root.organization_id = root.id
    everyone.organization_id = root.id
    outsider.organization_id = outsider.id

    _add(
        models.Module,
        name="core",
        blueprint=True,
        active=True,
        organization_id=root.id,
    )
    _add(
        models.DataType,
        id=STRING_TYPE_ID,
        name="string",
        active=True,
        organization_id=root.id,
        db_data_type="varchar",
    )
    _add(
        models.DataType,
        id=FILE_TYPE_ID,
        name="file",
        active=True,
        organization_id=root.id,
        db_data_type="varchar",
    )
    sample = _add(
        models.TableObject,
        name=TABLE,
        display_name="Sample Note",
        active=True,
        organization_id=root.id,
        admin_table=False,
    )
    db_session.flush()
    _add(
        models.Field,
        name=TABLE + "-name",
        active=True,
        organization_id=root.id,
        display_name="name",
        table_object_id=sample.id,
        data_type_id=STRING_TYPE_ID,
        primary_key=False,
        unique=False,
        length=100,
        default="",
        order=1,
    )
    _add(
        models.Field,
        name=TABLE + "-attachment",
        active=True,
        organization_id=root.id,
        display_name="attachment",
        table_object_id=sample.id,
        data_type_id=FILE_TYPE_ID,
        primary_key=False,
        unique=False,
        default="",
        order=2,
    )
    db_session.commit()
    db_session.remove()


def _seed_world(app):
    with app.app_context():
        root = db_session.query(models.Organization).filter_by(name="facility-root").one()
        everyone = db_session.query(models.Organization).filter_by(name="Everyone").one()
        outsider = db_session.query(models.Organization).filter_by(name="outsider-org").one()

        level = _add(
            models.Level,
            name="user",
            active=True,
            order=1,
            organization_id=root.id,
        )
        facility = _add(
            models.Facility,
            name="lab",
            active=True,
            organization_id=root.id,
            root_organization_id=root.id,
        )
        db_session.flush()
        role = _add(
            models.Role,
            name="lab-user",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            level_id=level.id,
        )
        db_session.flush()
        user = _add(
            models.User,
            name="html-reader",
            email=EMAIL,
            password=hash_password(PASSWORD),
            fs_uniquifier=uuid.uuid4().hex,
            active=True,
            verified=True,
            organization_id=root.id,
        )
        db_session.flush()
        user_role = _add(
            models.UserRole,
            name="html-reader-lab-user",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            role_id=role.id,
        )
        db_session.flush()
        user.current_user_role_id = user_role.id
        _add(
            models.UserOrganization,
            name="html-reader-root",
            active=True,
            organization_id=root.id,
            user_id=user.id,
            user_organization_id=root.id,
            default_organization=True,
        )

        module = db_session.query(models.Module).filter_by(name="core").one()
        _add(
            models.ModuleFacility,
            name="lab-core",
            active=True,
            organization_id=root.id,
            facility_id=facility.id,
            module_id=module.id,
        )
        route = _add(
            models.Route,
            name="core-summary",
            active=True,
            organization_id=root.id,
            module_id=module.id,
            url_path="summary",
        )
        db_session.flush()
        _add(
            models.RouteRole,
            name="role-summary",
            active=True,
            organization_id=root.id,
            role_id=role.id,
            route_id=route.id,
        )

        # get_table('table_object') reads this row to find the admin class.
        for meta_name in ("table_object", "table_object_role"):
            _add(
                models.TableObject,
                name=meta_name,
                active=True,
                organization_id=root.id,
                admin_table=True,
            )
        db_session.flush()
        sample = db_session.query(models.TableObject).filter_by(name=TABLE).one()
        _add(
            models.TableObjectRole,
            name="tor-" + TABLE,
            active=True,
            organization_id=root.id,
            role_id=role.id,
            table_object_id=sample.id,
            display_name="Sample Note",
        )
        fields = {
            row.display_name: row
            for row in db_session.query(models.Field).filter_by(table_object_id=sample.id)
        }
        for display_name, order in (("name", 1), ("attachment", 2)):
            field = fields[display_name]
            _add(
                models.FieldRole,
                name="fr-" + field.name,
                active=True,
                organization_id=root.id,
                role_id=role.id,
                field_id=field.id,
                display_name=display_name,
                visible=True,
                search_field=False,
                required=False,
                order=order,
            )

        _add(
            models.PageForm,
            name="save_message",
            active=True,
            organization_id=root.id,
            page_title="Saved",
            page_header="Saved",
            page_template="base.html",
        )
        for menu_name in ("AdminNavBar", "AdminSideBar"):
            _add(
                models.Menu,
                name=menu_name,
                active=True,
                organization_id=root.id,
                display_name=menu_name,
            )

        import iggybase.models as dynamic
        # Everyone is in org_ids. The outsider org is not a child of the facility root.
        visible = dynamic.SampleNote(
            name=STORED,
            active=True,
            organization_id=everyone.id,
            attachment=FILE_NAME,
        )
        hidden = dynamic.SampleNote(
            name="hidden-row",
            active=True,
            organization_id=outsider.id,
            attachment="hidden.txt",
        )
        db_session.add(visible)
        db_session.add(hidden)
        db_session.commit()


def _assert_escaped_anchor(testcase, text, visible):
    testcase.assertIn(visible, text)
    testcase.assertIn("<a ", text)
    testcase.assertNotIn("<script", text.lower())
    testcase.assertNotIn("&amp;lt;", text)


class StoredHtmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed_before_models()
        cls.app = create_app()
        cls.app.testing = True
        cls.app.config["PROPAGATE_EXCEPTIONS"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        # The download route writes CSV through flask_excel. The app does not
        # initialize that extension; the test does, so the response is a file.
        import flask_excel
        flask_excel.init_excel(cls.app)
        import iggybase.models as dynamic
        columns = set(dynamic.SampleNote.__table__.columns.keys())
        missing = {"name", "attachment", "organization_id"} - columns
        if missing:
            raise AssertionError("sample_note columns missing %s from %s" % (missing, columns))
        _seed_world(cls.app)

    def setUp(self):
        db_session.remove()

    @classmethod
    def tearDownClass(cls):
        db_session.remove()

    def test_summary_escapes_script_and_hides_other_org(self):
        client = self.app.test_client()
        self._login(client)
        response = client.get("/lab/core/summary/%s/ajax" % TABLE)
        body = response.get_data(as_text=True)
        response.close()
        self.assertEqual(200, response.status_code, body[:2000])
        payload = json.loads(body)
        self.assertEqual(1, len(payload["data"]), body[:2000])
        cells = [cell for row in payload["data"] for cell in row if isinstance(cell, str)]
        name_cells = [cell for cell in cells if "/detail/" in cell]
        file_cells = [cell for cell in cells if "/files/" in cell]
        self.assertEqual(1, len(name_cells), cells)
        self.assertEqual(1, len(file_cells), cells)
        _assert_escaped_anchor(self, name_cells[0], "&lt;script&gt;")
        _assert_escaped_anchor(self, file_cells[0], "&lt;script&gt;.txt")
        self.assertIn('target="_blank"', file_cells[0])
        self.assertNotIn("hidden-row", body)
        self.assertNotIn("hidden.txt", body)

    def test_download_keeps_the_raw_value(self):
        client = self.app.test_client()
        self._login(client)
        response = client.get("/lab/core/summary/%s/download/" % TABLE)
        body = response.get_data(as_text=True)
        response.close()
        self.assertEqual(200, response.status_code, body[:2000])
        self.assertIn(STORED, body)
        self.assertNotIn("<a ", body)
        self.assertNotIn("&lt;script&gt;", body)
        self.assertNotIn("hidden-row", body)

    def test_save_message_escapes_the_name(self):
        client = self.app.test_client()
        self._login(client)
        html, saved = self._save_message(client)
        _assert_escaped_anchor(self, html, "&lt;script&gt;")
        self.assertIn("%3Cscript%3E", html)
        self.assertEqual("%3Cscript%3E", saved[TABLE][0]["value"])
        self.assertNotIn("&lt;", saved[TABLE][0]["value"])

    def _login(self, client):
        login = client.post(
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "submit": "Login"},
        )
        self.assertIn(login.status_code, (302, 303), login.get_data(as_text=True)[:1500])

    def _save_message(self, client):
        """Call the real saved_data on an authenticated request and render it.

        modal_form skips the navbar. A one-role menu has no url, and that
        navbar is outside this slice. The page message block still renders.
        """
        from flask import render_template
        from iggybase.core.routes import saved_data

        cookie = client.get_cookie("session")
        if cookie is None:
            names = sorted(item[2] for item in client._cookies)
            self.fail("session cookie missing, have %s" % names)
        with self.app.test_request_context(
            "/lab/core/summary/%s/ajax" % TABLE,
            headers={"Cookie": "%s=%s" % (cookie.key, cookie.value)},
        ):
            blocked = self.app.preprocess_request()
            self.assertIsNone(blocked)
            context = saved_data(
                "lab",
                "core",
                TABLE,
                {1: {"id": 1, "name": STORED, "table": TABLE}},
                "modal_form",
                None,
            )
            saved = json.loads(context["saved_rows"])
            html = render_template(context["template"], **context)
        return html, saved


if __name__ == "__main__":
    unittest.main()
