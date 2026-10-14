"""User summary and detail for an admin.

The side menu item Users opens /<facility>/core/summary/user/. The name
column links to the detail screen. Rows are inserted when an admin role
already exists. home_page and the role default stay as they are, so the
stored home screen remains the landing page.

Security tests insert their own summary route after create_app, and they
have no admin role at that moment. Skipping until the role exists leaves
those later inserts alone.
"""

from sqlalchemy import text

from iggybase.admin import models
from iggybase.database import db_session

_LOCK = "iggybase_user_summary"


def _admin_roles(session):
    found = []
    for role in session.query(models.Role).all():
        if not role.active or not role.level_id:
            continue
        level = session.query(models.Level).filter_by(id=role.level_id).first()
        if level is None or not level.name:
            continue
        if level.name.strip().lower() == "admin":
            found.append(role)
    return found


def _get(session, model, **kwargs):
    return session.query(model).filter_by(**kwargs).first()


def _insert(session, model, **kwargs):
    row = model(**kwargs)
    session.add(row)
    session.flush()
    return row


def _named(session, model, name, **kwargs):
    row = _get(session, model, name=name)
    if row is None:
        row = _insert(session, model, name=name, **kwargs)
    return row


def _route(session, org_id, module_id, url_path, name, display_name):
    # url_path is unique. A route already stored under that path is the one
    # the screen uses, including a path inserted by something else first.
    row = _get(session, models.Route, url_path=url_path)
    if row is not None:
        return row
    if _get(session, models.Route, name=name) is not None:
        name = "%s-%s" % (name, url_path)
    return _insert(
        session,
        models.Route,
        name=name,
        description=display_name,
        active=True,
        organization_id=org_id,
        module_id=module_id,
        url_path=url_path,
        display_name=display_name,
    )


def _link(session, model, role, org_id, name, identity, extra=None):
    row = _get(session, model, role_id=role.id, **identity)
    if row is not None:
        return row
    # The same name may already point at this role. Leave that row in place.
    if _get(session, model, name=name) is not None:
        return None
    columns = {
        "name": name,
        "description": name,
        "active": True,
        "organization_id": role.organization_id or org_id,
        "role_id": role.id,
    }
    columns.update(identity)
    if extra:
        columns.update(extra)
    return _insert(session, model, **columns)


def ensure_user_summary():
    session = db_session()
    # Two gunicorn workers boot together. The lock keeps one insert of each name.
    locked = session.execute(text("SELECT GET_LOCK('%s', 15)" % _LOCK)).scalar()
    if int(locked or 0) != 1:
        db_session.remove()
        return
    try:
        core = _get(session, models.Module, name="core")
        if core is None:
            return
        organization = session.query(models.Organization).order_by(
            models.Organization.id
        ).first()
        if organization is None:
            return
        roles = _admin_roles(session)
        if not roles:
            return
        org_id = organization.id
        if not core.blueprint:
            core.blueprint = True

        data_type = _named(
            session,
            models.DataType,
            "string",
            description="string",
            active=True,
            organization_id=org_id,
            db_data_type="varchar",
        )
        for table_name in ("table_object", "table_object_role", "user"):
            _named(
                session,
                models.TableObject,
                table_name,
                description=table_name,
                active=True,
                organization_id=org_id,
                admin_table=True,
                display_name="User" if table_name == "user" else table_name,
            )
        user_table = _get(session, models.TableObject, name="user")

        summary_route = _route(
            session, org_id, core.id, "summary", "core-summary", "Summary"
        )
        detail_route = _route(
            session, org_id, core.id, "detail", "core-detail", "Detail"
        )
        summary_page = _named(
            session,
            models.PageForm,
            "summary",
            description="Users",
            active=True,
            organization_id=org_id,
            page_title="Users",
            page_header="Summary",
            page_template="summary.html",
        )
        _named(
            session,
            models.PageForm,
            "detail",
            description="Detail",
            active=True,
            organization_id=org_id,
            page_title="Detail",
            page_header="Detail",
            page_template="detail.html",
        )
        script = _get(
            session,
            models.PageFormJavascript,
            page_form_id=summary_page.id,
            page_javascript="summary.js",
        )
        if script is None:
            _named(
                session,
                models.PageFormJavascript,
                "summary-script",
                description="Summary",
                active=True,
                organization_id=org_id,
                page_form_id=summary_page.id,
                page_javascript="summary.js",
            )

        for menu_name in ("AdminNavBar", "AdminSideBar"):
            _named(
                session,
                models.Menu,
                menu_name,
                description=menu_name,
                active=True,
                organization_id=org_id,
                display_name=menu_name,
            )
        sidebar = _get(session, models.Menu, name="AdminSideBar")
        _named(
            session,
            models.Menu,
            "users-summary",
            description="Users",
            active=True,
            organization_id=org_id,
            parent_id=sidebar.id,
            route_id=summary_route.id,
            dynamic_suffix="user",
            display_name="Users",
            order=1,
        )
        users_menu = _get(session, models.Menu, name="users-summary")

        name_field = _named(
            session,
            models.Field,
            "user-name",
            description="name",
            active=True,
            organization_id=org_id,
            display_name="name",
            table_object_id=user_table.id,
            data_type_id=data_type.id,
            primary_key=False,
            unique=False,
            length=120,
            default="",
            order=1,
        )
        email_field = _named(
            session,
            models.Field,
            "user-email",
            description="email",
            active=True,
            organization_id=org_id,
            display_name="email",
            table_object_id=user_table.id,
            data_type_id=data_type.id,
            primary_key=False,
            unique=False,
            length=120,
            default="",
            order=2,
        )

        facilities = set()
        for role in roles:
            if role.facility_id:
                facilities.add(role.facility_id)
            _link(
                session, models.RouteRole, role, org_id,
                "%s-summary" % role.name, {"route_id": summary_route.id},
            )
            _link(
                session, models.RouteRole, role, org_id,
                "%s-detail" % role.name, {"route_id": detail_route.id},
            )
            _link(
                session, models.TableObjectRole, role, org_id,
                "%s-user" % role.name,
                {"table_object_id": user_table.id},
                {"display_name": "User"},
            )
            _link(
                session, models.MenuRole, role, org_id,
                "%s-users" % role.name,
                {"menu_id": users_menu.id},
                {"display_name": "Users"},
            )
            _link(
                session, models.FieldRole, role, org_id,
                "%s-user-name" % role.name,
                {"field_id": name_field.id},
                {
                    "display_name": "name",
                    "visible": True,
                    "search_field": True,
                    "required": False,
                    "order": 1,
                },
            )
            _link(
                session, models.FieldRole, role, org_id,
                "%s-user-email" % role.name,
                {"field_id": email_field.id},
                {
                    "display_name": "email",
                    "visible": True,
                    "search_field": False,
                    "required": False,
                    "order": 2,
                },
            )

        for facility_id in facilities:
            linked = _get(
                session,
                models.ModuleFacility,
                facility_id=facility_id,
                module_id=core.id,
            )
            if linked is not None:
                continue
            facility = _get(session, models.Facility, id=facility_id)
            if facility is None:
                continue
            facility_name = "%s-core" % facility.name
            if _get(session, models.ModuleFacility, name=facility_name) is not None:
                facility_name = "%s-%s" % (facility_name, facility.id)
            _insert(
                session,
                models.ModuleFacility,
                name=facility_name,
                description="core",
                active=True,
                organization_id=org_id,
                facility_id=facility.id,
                module_id=core.id,
            )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # GET_LOCK stays on the pooled connection until this runs.
        try:
            session.execute(text("SELECT RELEASE_LOCK('%s')" % _LOCK))
        except Exception:
            pass
        db_session.remove()
