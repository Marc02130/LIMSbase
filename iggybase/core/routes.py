import json
import logging
import os
import time
import urllib
from datetime import UTC, datetime
from importlib import import_module
from flask import request, jsonify, abort, g, render_template, current_app, redirect, send_from_directory, session, flash
from flask_wtf.csrf import validate_csrf
from markupsafe import Markup
from werkzeug.exceptions import NotFound
from werkzeug.security import safe_join
from wtforms import ValidationError
import flask_excel as excel
from flask_security import login_required
from iggybase import g_helper
from iggybase import utilities as util
from iggybase.web_files import forms
from iggybase.web_files.decorators import templated
from iggybase.web_files.form_generator import FormGenerator
from iggybase.web_files.form_parser import FormParser
from iggybase.web_files.modal_form import ModalForm
from iggybase.web_files.page_template import PageTemplate
from . import core
from .table_query import html_anchor
from .table_query_collection import TableQueryCollection
from .work_item_group import WorkItemGroup
from iggybase.core.constants import Timing

MODULE_NAME = 'core'


@core.route('/')
@login_required
def default(facility_name):
    pt = PageTemplate(MODULE_NAME, 'index.html')
    return pt.page_template_context('index.html')


@core.route('/summary/<table_name>/', defaults={'page_context': 'base-context'})
@core.route('/summary/<table_name>/<page_context>')
@login_required
@templated()
def summary(facility_name, table_name, page_context):
    page_form = 'summary'
    context = {'page_context': page_context}
    return build_summary(table_name, page_form, context)


@core.route('/summary/<table_name>/ajax')
@login_required
def summary_ajax(facility_name, table_name, page_form='summary', criteria={}):
    return build_summary_ajax(table_name, criteria)


@core.route('/action_summary/<table_name>/', defaults={'page_context': None}, methods=['GET', 'POST'])
@core.route('/action_summary/<table_name>/<page_context>', methods=['GET', 'POST'])
@login_required
@templated()
def action_summary(facility_name, table_name, page_context):
    page_form = 'action_summary'
    context = {'page_context': page_context}
    return build_summary(table_name, page_form, context)


@core.route('/action_summary/<table_name>/ajax')
@login_required
def action_summary_ajax(facility_name, table_name, page_form='action_summary', criteria={}):
    return build_summary_ajax(table_name, criteria)


@core.route('/detail/<table_name>/<row_name>', defaults={'page_context': 'base-context'})
@core.route('/detail/<table_name>/<row_name>/<page_context>/')
@login_required
@templated()
def detail(facility_name, table_name, row_name, page_context):
    criteria = {(table_name, 'name'): row_name}
    tqc = TableQueryCollection(table_name, criteria)
    tqc.get_results()
    add_row_id = False
    tqc.format_results(add_row_id)
    if not tqc.get_first().fc.fields:
        abort(404)
    if not tqc.get_first().get_first_row_dict():
        abort(403)
    hidden_fields = {'table': table_name, 'row_name': row_name}

    pt = PageTemplate(MODULE_NAME, 'detail', page_context)
    return pt.page_template_context(
        table_name=table_name,
        row_name=row_name,
        table_queries=tqc,
        hidden_fields=hidden_fields,
        page_context=page_context.split(',')
    )


@core.route('/summary/<table_name>/download/')
@login_required
def summary_download(facility_name, table_name):
    page_form = 'summary'
    add_row_id = False
    allow_links = False
    tqc = TableQueryCollection(table_name)
    tqc.get_results(allow_links)
    tqc.format_results(add_row_id, allow_links)
    tq = tqc.get_first()
    csv = excel.make_response_from_array(tq.results, 'csv')
    return csv

@core.route('/update_table_rows/<table_name>', methods=['GET', 'POST'])
@login_required
def update_table_rows(facility_name, table_name):
    # TODO: protect this by checking the rows ageninst org_ids
    updates = request.json['updates']
    message_fields = request.json['message_fields']
    criteria = {}
    tables = {}
    ids = request.json['ids']
    # ids is not all table ids, WARNING that
    # criteria will match all ids, not combinations of ids
    # however this seems just as reasonable as choosing an id per table
    # which must be done carefully in tq and could still be wrong
    # also we already use this for the row label
    tbl_ids = {}
    for id_row in ids:
        pairs = id_row.split('|')
        for pair_row in pairs:
            pair = pair_row.split('-')
            tup = (pair[0], 'id')
            if tup not in tables:
                criteria[tup] = []
            criteria[tup].append(pair[1])
            if tup not in tbl_ids:
                tbl_ids[tup] = {}
            if pair[1] not in tbl_ids[tup]:
                tbl_ids[tup][pair[1]] = []
            tbl_ids[tup][pair[1]].append(id_row)
    tqc = TableQueryCollection(table_name, criteria)
    tqc.get_results()
    tqc.format_results(True)
    tq = tqc.get_first()
    updated = tq.update_and_get_message(table_name, updates, criteria, message_fields, tbl_ids)
    return json.dumps({'updated': updated})

@core.route('/new_workflow/<workflow_name>/ajax', methods=['GET', 'POST'])
@login_required
def new_workflow(facility_name, workflow_name):
    wig = WorkItemGroup('new', workflow_name, 1)
    return json.dumps({'work_item_group': wig.name,
        'params':wig.workflow.steps[1].Step.params})

# TODO: maybe we should move this to the api module
@core.route('/get_row/<table_name>/ajax', methods=['GET', 'POST'])
@login_required
def get_row(facility_name, table_name):
    criteria = request.json['criteria']
    fields = request.json['fields']
    # A direct 404 skips the metadata error page, which 500s when that
    # page's rows are missing.
    if g_helper.get_role_access_control().has_access(
            'TableObject', {'name': table_name}) is None:
        return json.dumps({}), 404
    oac = g_helper.get_org_access_control()
    row = oac.get_row(table_name, criteria, org_ids=oac.org_ids)
    return json.dumps(util.column_values(row, fields))


@core.route('/search', methods=['GET', 'POST'])
@login_required
def search(facility_name):
    search_vals = json.loads(request.args.get('search_vals'))
    sf = ModalForm(search_vals)
    return sf.search_form()

@core.route('/search_results', methods=['GET', 'POST'])
@login_required
def search_results(facility_name):
    search_vals = json.loads(request.args.get('search_vals'))
    sf = ModalForm(search_vals)
    return sf.search_results()


def _owned_file(table_name, row_name, directory, filename):
    """Send a file only when that row's organization is in org_ids.

    The same empty 404 is used when the row is missing, out of org, or the
    file cannot be sent, so an out-of-org path is not distinguishable. A
    direct 404 skips the metadata error page.
    """
    if directory is None or not row_name:
        return '', 404
    oac = g_helper.get_org_access_control()
    row = oac.get_row(table_name, {'name': row_name}, org_ids=oac.org_ids)
    if row is None:
        return '', 404
    try:
        return send_from_directory(directory, filename)
    except NotFound:
        return '', 404


@core.route('/files/<table_name>/<row_name>/<filename>')
@login_required
def file_row(facility_name, table_name, row_name, filename):
    # safe_join keeps the table and row under FILE_FOLDER. send_from_directory
    # then keeps the filename inside that directory.
    directory = safe_join(current_app.config['FILE_FOLDER'], table_name, row_name)
    return _owned_file(table_name, row_name, directory, filename)

@core.route('/file/<table_name>/<filename>')
@login_required
def file(facility_name, table_name, filename):
    # Flat files are FILE_FOLDER / table / filename. The row name is the
    # filename without its extension.
    directory = safe_join(current_app.config['FILE_FOLDER'], table_name)
    row_name = os.path.splitext(filename)[0]
    return _owned_file(table_name, row_name, directory, filename)

@core.route('/change_role', methods=['POST'])
@login_required
def change_role(facility_name):
    role_id = request.json['role_id']
    rac = g_helper.get_role_access_control()
    success = rac.change_role(role_id)
    return json.dumps({'success': success})

@core.route('/change_user', methods=['POST'])
@login_required
def change_user(facility_name):
    rac = g_helper.get_role_access_control()
    if not rac.caller_is_admin():
        return json.dumps({'success': False})
    user_id = request.json['user_id']
    user = rac.change_user(user_id)
    success = False
    if user:
        oac = g_helper.get_org_access_control()
        session.pop('org_id', None)
        success = oac.set_user(user.User.id)
        if success:
            # Actor, target id, facility, and UTC time only. Not the body,
            # the password, or the session cookie.
            logging.getLogger('iggybase.audit').info(
                'change_user actor_id=%s target_id=%s facility=%s at=%s',
                rac.user.id,
                user.User.id,
                facility_name,
                datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            )
    return json.dumps({'success': success})

@core.route('/data_entry/<table_name>/<row_name>', defaults={'page_context': None}, methods=['GET', 'POST'])
@core.route('/data_entry/<table_name>/<row_name>/<page_context>', methods=['GET', 'POST'])
@login_required
@templated()
def data_entry(facility_name, table_name, row_name, page_context):
    module_name = MODULE_NAME
    if row_name == 'new':
        depth = request.args.get('depth', 0, int)
    else:
        depth = request.args.get('depth', 2, int)

    fg = FormGenerator('data_entry', 'SingleForm', table_name, page_context, module_name)
    fg.data_entry_form([row_name], None, depth)

    if request.method == 'POST' and fg.form_class.validate_csrf_data(request.form.get('csrf_token')):
        fp = FormParser(table_name)
        form_errors = fp.parse()

        fg.data_entry_form([row_name], fp.instances, depth)
        if form_errors:
            for form_id, error in form_errors.items():
                fg.form_class[form_id].errors = []
                fg.form_class[form_id].errors.append(error)

        if not fg.form_class.errors:
            save_status, save_msg = fp.save()

            if save_status is True:
                # TODO: here context is set in saved_data whereas for the form it is
                # set in fg.page_template_context - we should find a way to pass
                # the same base context for both post and get here
                return saved_data(facility_name, module_name, table_name, save_msg, page_context, fg)
            else:
                fg.add_page_context(save_msg)
                fp.undo()
        else:
            flash('Please fix validation errors below and save again.')
            fp.undo()

    return fg.page_template_context()


@core.route('/modal_add/<table_name>', defaults={'page_context': None}, methods=['GET', 'POST'])
@core.route('/modal_add/<table_name>/<page_context>', methods=['GET', 'POST'])
@login_required
@templated()
def modal_add(facility_name, table_name, page_context):
    module_name = MODULE_NAME
    if page_context:
        page_context += ",modal_form"
    else:
        page_context = "modal_form"

    fg = FormGenerator('modal_add', 'single', table_name, page_context, module_name)
    fg.data_entry_form('new', None, 0)

    return fg.page_template_context()


@core.route('/modal_add_submit/<table_name>', defaults={'page_context': None}, methods=['GET', 'POST'])
@core.route('/modal_add_submit/<table_name>/<page_context>', methods=['GET', 'POST'])
@login_required
def modal_add_submit(facility_name, table_name, page_context):
    fp = FormParser(table_name)
    fp.parse()
    save_status, save_msg = fp.save()

    return json.dumps({'error': not save_status})


def _submitted_csrf_ok():
    """True when the token on this POST matches the session token.

    The form field is preferred, matching Flask-WTF. The header is the token
    JavaScript sends. A failure must not reach FormParser.save.
    """
    token = request.form.get('csrf_token')
    if not token:
        token = request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
    try:
        validate_csrf(token)
    except ValidationError:
        return False
    return True


@core.route('/multiple_entry/<table_name>/<row_names>', defaults={'page_context': 'base-context'},
            methods=['GET', 'POST'])
@core.route('/multiple_entry/<table_name>/<row_names>/<page_context>', methods=['GET', 'POST'])
@login_required
@templated()
def multiple_entry(facility_name, table_name, row_names, page_context):
    module_name = MODULE_NAME
    row_names = json.loads(row_names)
    fg = FormGenerator('data_entry', 'MultipleForm', table_name, page_context, module_name)
    fg.data_entry_form(row_names)

    # Check the submitted token before the form is rebuilt. A failure skips
    # parse and save. A csrf_token error on the rebuilt form is left in place.
    if request.method == 'POST' and _submitted_csrf_ok():
        fp = FormParser(table_name)
        fp.parse()

        fg.data_entry_form(row_names, fp.instances)
        fg.form_class.validate_on_submit()

        field_errors = [name for name in fg.form_class.errors if name != 'csrf_token']
        if not field_errors:
            save_status, save_msg = fp.save()
            if save_status is True:
                return saved_data(facility_name, module_name, table_name, save_msg, page_context)
            else:
                fg.add_page_context(save_msg)
        else:
            fp.undo()

    return fg.page_template_context()


@core.route('/cache/', methods=['GET', 'POST'])
@login_required
@templated()
def cache(facility_name):
    # A signed-in caller is not enough. Only an admin may open this page.
    # set-key and set-version are not accepted from anyone, including an admin.
    rac = g_helper.get_role_access_control()
    if not rac.caller_is_admin():
        abort(403)
    module_name = MODULE_NAME
    form = forms.CacheForm()
    value = None
    if form.validate_on_submit() and len(form.errors) == 0:
        if 'get_value' in request.form and request.form['get_value']:
            if form.data['key']:
                value = current_app.cache.get(form.data['key'])
                if hasattr(value, 'data'):
                    value = value.data
        elif 'get_version' in request.form and request.form['get_version']:
            if form.data['refresh_obj']:
                value = str(current_app.cache.get_version(form.data['refresh_obj']))
            elif form.data['key']:
                value = str(current_app.cache.get_key_version(form.data['key']))

    pt = PageTemplate(MODULE_NAME, 'cache')

    return pt.page_template_context(module_name=module_name, form=form, value=value)


@core.route('/workflow/<workflow_name>/', defaults={'page_context': None})
@core.route('/workflow/<workflow_name>/<page_context>')
@login_required
@templated()
def workflow(facility_name, workflow_name, page_context):
    table_name = 'work_item_group'
    page_form = 'workflow_summary'

    context = {'btn_overrides': {'bottom':{'new':{'button_value':('New ' + workflow_name.title())}}}}
    context['hidden_fields'] = {'workflow_name': workflow_name}
    context['workflow_name'] = workflow_name
    context['page_context'] = 'workflow'
    if page_context:
        context['page_context'] += "," + page_context
    return build_summary(table_name, page_form, context)


@core.route('/workflow/<workflow_name>/ajax')
@login_required
def workflow_summary_ajax(facility_name, workflow_name, page_form='summary',
                          criteria={}):
    criteria = {('workflow', 'name'): workflow_name}
    table_name = 'work_item_group'
    return action_summary_ajax(facility_name, table_name, page_form, criteria)


@core.route('/workflow/<workflow_name>/<work_item_group>/complete')
@login_required
@templated()
def workflow_complete(facility_name, workflow_name, work_item_group):
    wig = WorkItemGroup(work_item_group, workflow_name)
    wig.set_review_items_link()
    pt = PageTemplate(MODULE_NAME, 'workflow_complete')

    return pt.page_template_context(wig=wig)


@core.route('/workflow/<workflow_name>/<step>/<work_item_group>', methods=['GET', 'POST'])
@login_required
def work_item_group(facility_name, workflow_name, step, work_item_group):
    wig = WorkItemGroup(work_item_group, workflow_name, int(step))
    wig.do_step_actions(Timing.BEFORE)
    logging.info('route work_item_group: ' + wig.name)
    if work_item_group == 'new':
        logging.info('route work_item_group is new ')
        return redirect(wig.workflow.get_step_url(1, wig.name))
    if 'next_step' in request.form:
        logging.info('route work_item_group is next_step ')
        wig.set_saved(json.loads(request.form['saved_rows']))
        next_step_url = wig.update_step()
        wig.do_step_actions(Timing.AFTER)
        return redirect(next_step_url)
    elif 'complete' in request.form:
        logging.info('route work_item_group is complete ')
        wig.set_saved(json.loads(request.form['saved_rows']))
        wig.set_complete()
        complete_url = wig.workflow.get_complete_url(wig.name)
        return redirect(complete_url)
    table_name = ''
    if wig.step.Module.name == MODULE_NAME:
        logging.info('route work_item_group is MODULE_NAME ')
        func = globals()[wig.step.Route.url_path]
    else:
        logging.info('route work_item_group is not MODULE_NAME ')
        module = import_module('iggybase.' + wig.step.Module.name + '.routes')
        func = getattr(module, wig.step.Route.url_path)

    logging.info('route wig.step.Route.url_path: ' + wig.step.Route.url_path)
    logging.info('route wig.dynamic_params:')
    logging.info(wig.dynamic_params)
    context = func(**wig.dynamic_params)
    wig.get_buttons(context['bottom_buttons'])
    if wig.buttons:
        logging.info('route work_item_group is wig.buttons ')
        context['bottom_buttons'].extend(wig.buttons)
    if 'saved_rows' in context:
        logging.info('route work_item_group is saved_rows ')
        wig.set_saved(context['saved_rows'])
    context['wig'] = wig
    return render_template('work_item_group.html', **context)


""" helper functions start """


def build_summary(table_name, page_form, context={}):
    tqc = TableQueryCollection(table_name)
    tq = tqc.get_first()
    if not tq.fc.fields:
        abort(404)

    pt = PageTemplate(MODULE_NAME, page_form, getattr(context, 'page_context', None))
    return pt.page_template_context(table_name=table_name, table_query=tq, **context)


def build_summary_ajax(table_name, criteria = {}):
    start = time.time()
    route = util.get_path(util.ROUTE)
    # TODO: we don't want oac instantiated multiple times
    oac = g_helper.get_org_access_control()
    current = time.time()
    print('oac: ' + str(current - start))
    ret = None
    filters = util.get_filters()
    key = current_app.cache.make_key(
        route,
        g.rac.role.id,
        oac.current_org_id,
        table_name
    )
    # criteria can be attached to the summary from DB
    # or filters can be added to the get params
    # both should clear the cache
    # TODO: add filters and criteria to cache
    print(filters)
    if (not criteria and not filters):
        print('checking cache: ' + key)
        ret = current_app.cache.get(key)
    if not ret:
        print('cache miss')
        tqc = TableQueryCollection(table_name, criteria)
        current = time.time()
        print('through collection: ' + str(current - start))
        tqc.get_results()
        current = time.time()
        print('get_results: ' + str(current - start))
        tqc.format_results()
        current = time.time()
        print('format_results: ' + str(current - start))
        table_query = tqc.get_first()
        current = time.time()
        print(str(current - start))
        json_rows = table_query.results
        current = time.time()
        print(str(current - start))
        ret = json.dumps({'data': json_rows}, cls=util.CustomEncoder)
        if (('clear_cache' in filters and len(filters) ==1) or
        (not criteria and not filters)):
            print('caching: ' + key)
            current_app.cache.set(key, ret, (24 * 60 * 60), [table_name])
    else:
        print('cache hit: ' + key)
    return ret


def saved_data(facility_name, module_name, table_name, row_names,
        page_context, fg):
    # page_msg is marked safe in the template, so the name and the URL are
    # escaped before they are wrapped in the anchor. saved_rows keeps the
    # URL-quoted name.
    msg = Markup('Saved:')
    error = False
    saved_rows = {}
    for row_info in row_names.values():
        if row_info['name'] == 'error':

            msg = 'Error: %s,' % str(row_info['table']).replace('<', '').replace('>', '')
            error = True
        else:
            table = urllib.parse.quote(row_info['table'])
            name = urllib.parse.quote(row_info['name'])
            href = (request.url_root + facility_name + '/' + module_name +
                    '/detail/' + table + '/' + name)
            msg += Markup(' ') + html_anchor(href, row_info['name']) + Markup(',')

            # TODO: allow this to support data saving by other than name
            if not table in saved_rows:
                saved_rows[table] = []
            saved_rows[table].append({
                'column': 'name',
                'value': name,
                'id': row_info['id'],
                'table': table
            })
    msg = msg[:-1]

    if error:
        pt = PageTemplate(MODULE_NAME, 'error_message', page_context)
        return pt.page_template_context(table_name=table_name, page_msg=msg)
    else:
        pt = PageTemplate(MODULE_NAME, 'save_message', page_context)
        return pt.page_template_context(table_name=table_name, page_msg=msg, saved_rows=json.dumps(saved_rows))

