import base64
import os

from werkzeug.exceptions import NotFound

from odoo import _, fields
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request, route
from odoo.addons.portal.controllers.portal import CustomerPortal

from ..models.eaut_admission_application import PERSONAL_FIELDS, STATES
from ..models.eaut_admission_document import (
    ALLOWED_EXTENSIONS, DOC_TYPES, MAX_FILE_SIZE, SINGLE_DOC_TYPES,
)

EDITABLE_FIELDS = PERSONAL_FIELDS
DATE_FIELDS = ('date_of_birth', 'id_issue_date')
REQUIRED_FORM_FIELDS = ['full_name', 'phone', 'email']
# Giới hạn số tệp mỗi lần nộp để tránh lạm dụng form công khai
MAX_FILES_PER_SUBMIT = 15

class EautAdmissionPortal(CustomerPortal):

    # =========================================================
    # HELPERS
    # =========================================================

    def _flash(self, message, level='success'):
        request.session['eaut_admission_flash'] = {'message': message, 'level': level}

    def _pop_flash(self):
        return request.session.pop('eaut_admission_flash', None)

    def _get_application(self, app_id, access_token=None):
        """Truy cập hồ sơ bằng access_token trong link email (hoặc tài khoản chủ hồ sơ); trả về record sudo."""
        try:
            app = self._document_check_access(
                'eaut.admission.application', app_id, access_token or None)
        except (AccessError, MissingError):
            raise NotFound()
        return app.sudo()

    def _back(self, app, access_token=None):
        url = '/my/admission/%s' % app.id
        if access_token:
            url += '?access_token=%s' % access_token
        return request.redirect(url)

    def _get_editable_application(self, app_id, access_token=None):
        app = self._get_application(app_id, access_token)
        if app.state != 'draft':
            self._flash(_("Hồ sơ đang được nhà trường xử lý nên không thể chỉnh sửa."), 'danger')
            return app, self._back(app, access_token)
        return app, None

    def _open_campaigns(self):
        """Chiến dịch đang mở nhận hồ sơ: còn hoạt động, trong thời gian tuyển sinh và có form đang bật."""
        today = fields.Date.today()
        campaigns = request.env['eaut.crm.admission.campaign'].sudo().search([('active', '=', True)])
        return campaigns.filtered(
            lambda c: (not c.date_start or c.date_start <= today)
            and (not c.date_end or c.date_end >= today)
            and c.admission_form_ids.filtered('active')
        )

    def _get_open_form(self, form_token):
        form = request.env['eaut.crm.admission.campaign.form'].sudo().search(
            [('token', '=', form_token), ('active', '=', True)], limit=1)
        if not form or form.campaign_id not in self._open_campaigns():
            return None
        return form

    def _run_safely(self, func):
        """Chạy thao tác ghi trong savepoint để lỗi ràng buộc không làm lưu dữ liệu dở dang."""
        try:
            with request.env.cr.savepoint():
                func()
            return True
        except (ValidationError, UserError) as exc:
            self._flash(exc.args[0] if exc.args else str(exc), 'danger')
            return False

    def _parse_personal_vals(self, post):
        """Chuyển dữ liệu form thành vals; ném ValidationError nếu sai kiểu."""
        vals = {}
        for fname in EDITABLE_FIELDS:
            if fname not in post:
                continue
            value = (post[fname] or '').strip()
            if fname == 'graduation_year':
                if value and not value.isdigit():
                    raise ValidationError(_("Năm tốt nghiệp phải là số."))
                value = int(value) if value else 0
            elif fname in DATE_FIELDS:
                try:
                    value = fields.Date.to_date(value) if value else False
                except ValueError:
                    raise ValidationError(_("Ngày nhập không hợp lệ."))
            else:
                value = value or False
            vals[fname] = value
        return vals

    def _read_upload(self, upload):
        """Kiểm tra và đọc 1 tệp upload; trả về (tên tệp, nội dung base64)."""
        filename = os.path.basename(upload.filename)
        if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
            raise ValidationError(_("Chỉ chấp nhận tệp: %s") % ', '.join(ALLOWED_EXTENSIONS))
        data = upload.read(MAX_FILE_SIZE + 1)
        if len(data) > MAX_FILE_SIZE:
            raise ValidationError(
                _("Tệp %(name)s vượt quá dung lượng tối đa %(size)s MB.",
                  name=filename, size=MAX_FILE_SIZE // (1024 * 1024)))
        if not data:
            raise ValidationError(_("Tệp %s rỗng.") % filename)
        return filename, base64.b64encode(data)

    def _app_to_vals(self, app):
        """Giá trị hiển thị của form (chuỗi) lấy từ hồ sơ."""
        vals = {}
        for fname in EDITABLE_FIELDS:
            value = app[fname]
            vals[fname] = str(value) if value else ''
        return vals

    def _form_context(self, **extra):
        env = request.env
        values = {
            'programs': env['eaut.crm.admission.program'].sudo().search([('active', '=', True)]),
            'methods': env['eaut.crm.admission.method'].sudo().search([('active', '=', True)]),
            'combinations': env['eaut.crm.admission.combination'].sudo().search([('active', '=', True)]),
            'doc_types': DOC_TYPES,
            'single_doc_types': SINGLE_DOC_TYPES,
            'allowed_extensions': ','.join(ALLOWED_EXTENSIONS),
            'max_choices': env['eaut.admission.application'].MAX_CHOICES,
            'max_file_mb': MAX_FILE_SIZE // (1024 * 1024),
        }
        values.update(extra)
        return values

    @staticmethod
    def _mask_email(email):
        name, _at, domain = (email or '').partition('@')
        return '%s***@%s' % (name[:2], domain) if domain else ''

    # =========================================================
    # FORM CÔNG KHAI không cần tài khoản
    # =========================================================

    @route('/admission/apply', type='http', auth='public', website=True)
    def admission_apply_list(self, **kw):
        return request.render('eaut_admission.admission_apply_list', {
            'campaigns': self._open_campaigns(),
        })

    @route('/admission/apply/<string:form_token>', type='http', auth='public', website=True)
    def admission_apply_form(self, form_token, **kw):
        form = self._get_open_form(form_token)
        if not form:
            return request.render('eaut_admission.admission_apply_closed')
        return request.render('eaut_admission.admission_apply_form', self._form_context(
            form=form, vals={}, error=None,
        ))

    @route('/admission/apply/<string:form_token>/submit', type='http', auth='public',
           website=True, methods=['POST'])
    def admission_apply_submit(self, form_token, **post):
        form = self._get_open_form(form_token)
        if not form:
            return request.render('eaut_admission.admission_apply_closed')

        # Ô bẫy bot: người thật không nhìn thấy nên không điền
        if post.get('website_url'):
            return self._render_submitted(None, None)

        def _rerender(error):
            return request.render('eaut_admission.admission_apply_form', self._form_context(
                form=form, vals=post, error=error,
            ))

        try:
            vals = self._parse_personal_vals(post)
            missing = [f for f in REQUIRED_FORM_FIELDS if not vals.get(f)]
            if missing:
                raise ValidationError(_("Vui lòng nhập đầy đủ họ tên, số điện thoại và email."))
            vals['phone'] = request.env['eaut.crm.lead']._normalize_phone(vals['phone'])
            choices = self._parse_choices(post)
            documents = self._parse_documents()
        except ValidationError as exc:
            return _rerender(exc.args[0])

        Application = request.env['eaut.admission.application'].sudo()
        existing = Application.with_context(active_test=False).search([
            ('phone', '=', vals['phone']), ('campaign_id', '=', form.campaign_id.id),
        ], limit=1)
        if existing:
            # Đã có hồ sơ: chỉ gửi lại link theo dõi vào email đã lưu, không tiết lộ dữ liệu
            existing._log_submission(
                'duplicate', form=form, vals=vals, choices=choices, documents=documents,
                ip=request.httprequest.remote_addr)

        created = {}

        def _create():
            app = Application.create(dict(
                vals,
                campaign_id=form.campaign_id.id,
                campaign_form_id=form.id,
                choice_ids=[(0, 0, c) for c in choices],
                document_ids=[(0, 0, d) for d in documents],
            ))
            app.action_submit()
            app._log_submission(
                'new', form=form, vals=vals, choices=choices, documents=documents,
                ip=request.httprequest.remote_addr)
            created['app'] = app

            try:
                with request.env.cr.savepoint():
                    _create()
            except (ValidationError, UserError) as exc:
                return _rerender(exc.args[0] if exc.args else str(exc))
            return self._render_submitted(created['app'].name, created['app'].email)

        def _parse_choices(self, post):
            choices = []
            max_choices = request.env['eaut.admission.application'].MAX_CHOICES
            for index in range(1, max_choices + 1):
                program_id = post.get('program_id_%s' % index)
                method_id = post.get('method_id_%s' % index)
                if not program_id and not method_id:
                    continue
                if not program_id or not method_id:
                    raise ValidationError(
                        _("Nguyện vọng %s cần chọn đủ ngành học và phương thức xét tuyển.") % index)
                try:
                    score = float((post.get('score_%s' % index) or '0').replace(',', '.') or 0)
                    choices.append({
                        'priority': len(choices) + 1,
                        'program_id': int(program_id),
                        'method_id': int(method_id),
                        'combination_id': int(post.get('combination_id_%s' % index) or 0) or False,
                        'score': score,
                    })
                except ValueError:
                    raise ValidationError(_("Nguyện vọng %s có dữ liệu không hợp lệ.") % index)
            if not choices:
                raise ValidationError(_("Vui lòng chọn ít nhất một nguyện vọng xét tuyển."))
            return choices

        def _parse_documents(self):
            documents = []
            for doc_type, _label in DOC_TYPES:
                uploads = [
                    f for f in request.httprequest.files.getlist('file_%s' % doc_type) if f and f.filename
                ]
                if doc_type in SINGLE_DOC_TYPES:
                    uploads = uploads[:1]
                for upload in uploads:
                    filename, data = self._read_upload(upload)
                    documents.append({'doc_type': doc_type, 'file': data, 'file_name': filename})
            if len(documents) > MAX_FILES_PER_SUBMIT:
                raise ValidationError(_("Chỉ được tải lên tối đa %s tệp.") % MAX_FILES_PER_SUBMIT)
            return documents

        def _render_submitted(self, name, email):
            return request.render('eaut_admission.admission_submitted', {
                'application_name': name,
                'email_hint': self._mask_email(email),
            })

    # =========================================================
    # CHI TIẾT HỒ SƠ
    # =========================================================

    @route('/my/admission/<int:app_id>', type='http', auth='public', website=True)
    def portal_admission_detail(self, app_id, access_token=None, **kw):
        app = self._get_application(app_id, access_token)
        step_keys = [key for key, _label in STATES]
        values = self._form_context(
            app=app,
            vals=self._app_to_vals(app),
            editable=app.state == 'draft',
            steps=STATES,
            current_step=step_keys.index(app.state),
            missing=app._get_missing_items(),
            flash=self._pop_flash(),
        )
        values = self._get_page_view_values(
            app, access_token, values, 'my_admission_history', True, **kw)
        return request.render('eaut_admission.portal_admission_detail', values)

    @route('/my/admission/<int:app_id>/save', type='http', auth='public', website=True, methods=['POST'])
    def portal_admission_save(self, app_id, access_token=None, **post):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect
        try:
            vals = self._parse_personal_vals(post)
        except ValidationError as exc:
            self._flash(exc.args[0], 'danger')
            return self._back(app, access_token)
        if self._run_safely(lambda: app.write(vals)):
            self._flash(_("Đã lưu thông tin."))
        return self._back(app, access_token)

    # =========================================================
    # NGUYỆN VỌNG
    # =========================================================

    @route('/my/admission/<int:app_id>/choice/add', type='http', auth='public', website=True, methods=['POST'])
    def portal_admission_choice_add(self, app_id, access_token=None, program_id=None, method_id=None,
                                    combination_id=None, score=None, **kw):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect
        env = request.env
        program = env['eaut.crm.admission.program'].sudo().search(
            [('id', '=', int(program_id or 0)), ('active', '=', True)])
        method = env['eaut.crm.admission.method'].sudo().search(
            [('id', '=', int(method_id or 0)), ('active', '=', True)])
        combination = env['eaut.crm.admission.combination'].sudo().search(
            [('id', '=', int(combination_id or 0)), ('active', '=', True)])
        if not program or not method:
            self._flash(_("Vui lòng chọn ngành và phương thức xét tuyển."), 'danger')
            return self._back(app, access_token)
        try:
            score_value = float((score or '0').replace(',', '.') or 0)
        except ValueError:
            self._flash(_("Điểm không hợp lệ."), 'danger')
            return self._back(app, access_token)
        if len(app.choice_ids) >= app.MAX_CHOICES:
            self._flash(_("Chỉ được đăng ký tối đa %s nguyện vọng.") % app.MAX_CHOICES, 'danger')
            return self._back(app, access_token)

        def _add():
            env['eaut.admission.choice'].sudo().create({
                'application_id': app.id,
                'priority': len(app.choice_ids) + 1,
                'program_id': program.id,
                'method_id': method.id,
                'combination_id': combination.id or False,
                'score': score_value,
            })

        if self._run_safely(_add):
            self._flash(_("Đã thêm nguyện vọng."))
        return self._back(app, access_token)

    @route('/my/admission/<int:app_id>/choice/<int:choice_id>/delete', type='http',
           auth='public', website=True, methods=['POST'])
    def portal_admission_choice_delete(self, app_id, choice_id, access_token=None, **kw):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect
        app.choice_ids.filtered(lambda c: c.id == choice_id).unlink()
        # Đánh lại thứ tự nguyện vọng cho liên tục
        for index, choice in enumerate(app.choice_ids.sorted('priority'), start=1):
            if choice.priority != index:
                choice.priority = index
        self._flash(_("Đã xóa nguyện vọng."))
        return self._back(app, access_token)

    # =========================================================
    # TÀI LIỆU
    # =========================================================

    @route('/my/admission/<int:app_id>/upload', type='http', auth='public', website=True, methods=['POST'])
    def portal_admission_upload(self, app_id, access_token=None, doc_type=None, **post):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect

        upload = request.httprequest.files.get('file')
        if doc_type not in dict(DOC_TYPES) or not upload or not upload.filename:
            self._flash(_("Vui lòng chọn loại giấy tờ và tệp cần tải lên."), 'danger')
            return self._back(app, access_token)
        try:
            filename, data = self._read_upload(upload)
        except ValidationError as exc:
            self._flash(exc.args[0], 'danger')
            return self._back(app, access_token)

        def _upload():
            if doc_type in SINGLE_DOC_TYPES:
                app.document_ids.filtered(lambda d: d.doc_type == doc_type).unlink()
            request.env['eaut.admission.document'].sudo().create({
                'application_id': app.id,
                'doc_type': doc_type,
                'file': data,
                'file_name': filename,
            })

        if self._run_safely(_upload):
            self._flash(_("Đã tải lên tệp %s.") % filename)
        return self._back(app, access_token)

    @route('/my/admission/<int:app_id>/document/<int:doc_id>/delete', type='http',
           auth='public', website=True, methods=['POST'])
    def portal_admission_document_delete(self, app_id, doc_id, access_token=None, **kw):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect
        app.document_ids.filtered(lambda d: d.id == doc_id).unlink()
        self._flash(_("Đã xóa tệp."))
        return self._back(app, access_token)

    @route('/my/admission/<int:app_id>/document/<int:doc_id>/download', type='http',
           auth='public', website=True)
    def portal_admission_document_download(self, app_id, doc_id, access_token=None, **kw):
        app = self._get_application(app_id, access_token)
        doc = app.document_ids.filtered(lambda d: d.id == doc_id)
        if not doc:
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(doc, 'file', 'file_name')
        return stream.get_response(as_attachment=True)

    # =========================================================
    # NỘP HỒ SƠ & GIẤY XÁC NHẬN NHẬP HỌC
    # =========================================================

    @route('/my/admission/<int:app_id>/submit', type='http', auth='public', website=True, methods=['POST'])
    def portal_admission_submit(self, app_id, access_token=None, **kw):
        app, redirect = self._get_editable_application(app_id, access_token)
        if redirect:
            return redirect
        def _resubmit():
            app.action_submit()
            app._log_submission('resubmit', ip=request.httprequest.remote_addr)

        if self._run_safely(_resubmit):
            self._flash(_("Hồ sơ đã được gửi lại tới nhà trường. Vui lòng chờ kiểm tra."))
        return self._back(app, access_token)

    @route('/my/admission/<int:app_id>/letter', type='http', auth='public', website=True)
    def portal_admission_letter(self, app_id, access_token=None, **kw):
        app = self._get_application(app_id, access_token)
        if not app.admission_letter_available:
            self._flash(
                _("Giấy xác nhận nhập học chỉ được cấp khi bạn đã đóng học phí và đỗ tốt nghiệp."), 'danger')
            return self._back(app, access_token)
        pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'eaut_admission.action_report_admission_letter', [app.id])
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', 'attachment; filename="Giay-xac-nhan-nhap-hoc-%s.pdf"' % app.name),
        ]
        return request.make_response(pdf, headers=headers)