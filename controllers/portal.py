# -*- coding: utf-8 -*-
import base64
import os

from werkzeug.exceptions import NotFound

from odoo import _, fields
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import request, route
from odoo.addons.portal.controllers.portal import CustomerPortal

from ..models.eaut_admission_application import PERSONAL_FIELDS, STATES
from ..models.eaut_admission_document import (
    ALLOWED_EXTENSIONS, DOC_TYPES, MAX_FILE_SIZE, REQUIRED_DOC_TYPES,
)

DATE_FIELDS = ('date_of_birth', 'id_issue_date')
REQUIRED_FIELDS = ['full_name', 'phone', 'email']
MAX_CHOICES = 3
MAX_FILES = 10


class EautAdmissionPortal(CustomerPortal):

    # =========================================================
    # FORM CÔNG KHAI (không cần tài khoản)
    # =========================================================

    def _open_campaigns(self):
        """Chiến dịch đang mở: còn hoạt động, trong thời gian tuyển sinh, có form đang bật."""
        today = fields.Date.today()
        campaigns = request.env['eaut.crm.admission.campaign'].sudo().search([('active', '=', True)])
        return campaigns.filtered(
            lambda c: (not c.date_start or c.date_start <= today)
            and (not c.date_end or c.date_end >= today)
            and c.admission_form_ids.filtered('active')
        )

    def _get_open_form(self, token):
        form = request.env['eaut.crm.admission.campaign.form'].sudo().search(
            [('token', '=', token), ('active', '=', True)], limit=1)
        return form if form and form.campaign_id in self._open_campaigns() else None

    def _form_values(self, form, vals=None, error=None):
        env = request.env
        return {
            'form': form,
            'vals': vals or {},
            'error': error,
            'choice_numbers': range(1, MAX_CHOICES + 1),
            'programs': env['eaut.crm.admission.program'].sudo().search([('active', '=', True)]),
            'methods': env['eaut.crm.admission.method'].sudo().search([('active', '=', True)]),
            'combinations': env['eaut.crm.admission.combination'].sudo().search([('active', '=', True)]),
            'doc_types': DOC_TYPES,
            'required_doc_types': REQUIRED_DOC_TYPES,
            'allowed_extensions': ','.join(ALLOWED_EXTENSIONS),
            'max_file_mb': MAX_FILE_SIZE // (1024 * 1024),
        }

    @route('/admission/apply', type='http', auth='public', website=True)
    def admission_apply_list(self, **kw):
        return request.render('eaut_admission.admission_apply_list', {'campaigns': self._open_campaigns()})

    @route('/admission/apply/<string:form_token>', type='http', auth='public', website=True)
    def admission_apply_form(self, form_token, **kw):
        form = self._get_open_form(form_token)
        if not form:
            return request.render('eaut_admission.admission_apply_closed')
        return request.render('eaut_admission.admission_apply_form', self._form_values(form))

    @route('/admission/apply/<string:form_token>/submit', type='http', auth='public',
           website=True, methods=['POST'])
    def admission_apply_submit(self, form_token, **post):
        form = self._get_open_form(form_token)
        if not form:
            return request.render('eaut_admission.admission_apply_closed')
        if post.get('website_url'):  # ô bẫy bot: người thật không điền
            return request.render('eaut_admission.admission_submitted', {})

        try:
            vals = self._parse_vals(post)
            choices = self._parse_choices(post)
            documents = self._parse_documents()
            with request.env.cr.savepoint():
                app = request.env['eaut.admission.application'].sudo().create(dict(
                    vals,
                    campaign_id=form.campaign_id.id,
                    campaign_form_id=form.id,
                    choice_ids=[(0, 0, c) for c in choices],
                    document_ids=[(0, 0, d) for d in documents],
                ))
        except ValidationError as exc:
            return request.render('eaut_admission.admission_apply_form',
                                  self._form_values(form, vals=post, error=exc.args[0]))

        app._send_tracking_email()
        return request.render('eaut_admission.admission_submitted', {'app': app})

    def _parse_vals(self, post):
        vals = {}
        for fname in PERSONAL_FIELDS:
            value = (post.get(fname) or '').strip()
            if fname == 'graduation_year':
                if value and not value.isdigit():
                    raise ValidationError(_("Năm tốt nghiệp phải là số."))
                value = int(value) if value else 0
            elif fname in DATE_FIELDS:
                try:
                    value = fields.Date.to_date(value) if value else False
                except ValueError:
                    raise ValidationError(_("Ngày nhập không hợp lệ."))
            vals[fname] = value or False
        if not all(vals[f] for f in REQUIRED_FIELDS):
            raise ValidationError(_("Vui lòng nhập đầy đủ họ tên, số điện thoại và email."))
        return vals

    @staticmethod
    def _to_int(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _parse_choices(self, post):
        env = request.env
        choices = []
        for n in range(1, MAX_CHOICES + 1):
            program_id, method_id = post.get('program_id_%s' % n), post.get('method_id_%s' % n)
            if not program_id and not method_id:
                continue
            program = env['eaut.crm.admission.program'].sudo().search(
                [('id', '=', self._to_int(program_id)), ('active', '=', True)])
            method = env['eaut.crm.admission.method'].sudo().search(
                [('id', '=', self._to_int(method_id)), ('active', '=', True)])
            combination = env['eaut.crm.admission.combination'].sudo().search(
                [('id', '=', self._to_int(post.get('combination_id_%s' % n))), ('active', '=', True)])
            if not program or not method:
                raise ValidationError(
                    _("Nguyện vọng %s cần chọn đủ ngành học và phương thức xét tuyển.") % n)
            choices.append({
                'priority': len(choices) + 1,
                'program_id': program.id,
                'method_id': method.id,
                'combination_id': combination.id or False,
            })
        if not choices:
            raise ValidationError(_("Vui lòng chọn ít nhất một nguyện vọng xét tuyển."))
        return choices

    def _parse_documents(self):
        labels = dict(DOC_TYPES)
        documents = []
        for doc_type in labels:
            uploads = [f for f in request.httprequest.files.getlist('file_%s' % doc_type)
                       if f and f.filename]
            if doc_type in REQUIRED_DOC_TYPES and not uploads:
                raise ValidationError(_("Vui lòng tải lên: %s") % labels[doc_type])
            for upload in uploads:
                filename = os.path.basename(upload.filename)
                if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
                    raise ValidationError(_("Chỉ chấp nhận tệp: %s") % ', '.join(ALLOWED_EXTENSIONS))
                data = upload.read(MAX_FILE_SIZE + 1)
                if not data or len(data) > MAX_FILE_SIZE:
                    raise ValidationError(
                        _("Tệp %(name)s rỗng hoặc vượt quá %(size)s MB.",
                          name=filename, size=MAX_FILE_SIZE // (1024 * 1024)))
                documents.append({
                    'doc_type': doc_type, 'file': base64.b64encode(data), 'file_name': filename})
        if len(documents) > MAX_FILES:
            raise ValidationError(_("Chỉ được tải lên tối đa %s tệp.") % MAX_FILES)
        return documents

    # =========================================================
    # TRANG THEO DÕI HỒ SƠ (link trong email, có access_token)
    # =========================================================

    def _get_application(self, app_id, access_token=None):
        try:
            return self._document_check_access('eaut.admission.application', app_id, access_token or None)
        except (AccessError, MissingError):
            raise NotFound()

    @route('/my/admission/<int:app_id>', type='http', auth='public', website=True)
    def portal_admission_detail(self, app_id, access_token=None, **kw):
        app = self._get_application(app_id, access_token)
        values = {
            'app': app,
            'steps': STATES,
            'current_step': [key for key, _label in STATES].index(app.state),
            'state_label': dict(STATES)[app.state],
            'doc_labels': dict(DOC_TYPES),
            'access_token': access_token,
        }
        values = self._get_page_view_values(app, access_token, values, 'my_admission_history', True, **kw)
        return request.render('eaut_admission.portal_admission_detail', values)

    @route('/my/admission/<int:app_id>/document/<int:doc_id>/download', type='http',
           auth='public', website=True)
    def portal_admission_document_download(self, app_id, doc_id, access_token=None, **kw):
        app = self._get_application(app_id, access_token)
        doc = app.document_ids.filtered(lambda d: d.id == doc_id)
        if not doc:
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(doc, 'file', filename_field='file_name')
        return stream.get_response(as_attachment=True)
