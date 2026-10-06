"""Stored home screen.

The navbar Home link goes to /home, which redirects to the signed-in user's
home_page, or the role default when that is empty. This makes sure that
target is the core home screen, not the cache inspector.
"""

from sqlalchemy import text

from iggybase.admin import models
from iggybase.database import db_session

# Fits page_form.description (varchar 255). The home template prints it.
HOME_BLURB = (
    "Iggybase is a laboratory information system. What people can see and do "
    "is stored as tables, menus, and roles.\n"
    "A lab can change those records instead of writing a new program for every "
    "change. This copy is being brought back as its own project."
)


def home_path(facility_name):
    return "/%s/core/home/" % facility_name


def _is_unset_or_cache(path, facility_name):
    if not path:
        return True
    return path.rstrip("/") == "/%s/core/cache" % facility_name


def ensure_stored_home():
    session = db_session()
    # Two gunicorn workers boot together. Without the lock both insert the
    # same page name and one of them takes the process down.
    locked = session.execute(
        text("SELECT GET_LOCK('iggybase_stored_home', 15)")
    ).scalar()
    if int(locked or 0) != 1:
        db_session.remove()
        return
    try:
        core = session.query(models.Module).filter_by(name="core").first()
        if core is None:
            return
        organization = session.query(models.Organization).order_by(
            models.Organization.id
        ).first()
        if organization is None:
            return
        org_id = organization.id

        page = session.query(models.PageForm).filter_by(name="home").first()
        if page is None:
            page = models.PageForm(
                name="home",
                description=HOME_BLURB,
                active=True,
                organization_id=org_id,
                page_title="Iggybase",
                page_header="Iggybase",
                page_template="home.html",
            )
            session.add(page)

        route = session.query(models.Route).filter_by(url_path="home").first()
        if route is None:
            route = models.Route(
                name="core-home",
                description="Home",
                active=True,
                organization_id=org_id,
                module_id=core.id,
                url_path="home",
                display_name="Home",
            )
            session.add(route)
            session.flush()

        facilities = session.query(models.Facility).all()
        for facility in facilities:
            path = home_path(facility.name)
            roles = session.query(models.Role).filter_by(
                facility_id=facility.id
            ).all()
            for role in roles:
                if not role.active:
                    continue
                if len(path) <= 100 and _is_unset_or_cache(role.default_home, facility.name):
                    role.default_home = path
                link = session.query(models.RouteRole).filter_by(
                    role_id=role.id, route_id=route.id
                ).first()
                if link is None:
                    session.add(models.RouteRole(
                        name="%s-home" % role.name,
                        description="Home",
                        active=True,
                        organization_id=role.organization_id or org_id,
                        role_id=role.id,
                        route_id=route.id,
                    ))

        users = session.query(models.User).all()
        for user in users:
            if not user.current_user_role_id:
                continue
            membership = session.query(models.UserRole).filter_by(
                id=user.current_user_role_id
            ).first()
            if membership is None:
                continue
            role = session.query(models.Role).filter_by(id=membership.role_id).first()
            if role is None or role.facility_id is None:
                continue
            facility = session.query(models.Facility).filter_by(
                id=role.facility_id
            ).first()
            if facility is None:
                continue
            path = home_path(facility.name)
            if len(path) <= 50 and _is_unset_or_cache(user.home_page, facility.name):
                user.home_page = path

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # GET_LOCK stays on the pooled connection until this runs. The other
        # worker is waiting on that same name.
        try:
            session.execute(text("SELECT RELEASE_LOCK('iggybase_stored_home')"))
        except Exception:
            pass
        db_session.remove()
