# -*- coding: utf-8 -*-
import base64
import os

from werkzeug.exceptions import NotFound

from odoo import _, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request, route
from odoo.addons.portal.controllers.portal import CustomerPortal

from ..models.eaut_admission_application import STATES
from ..models.eaut_admission_document import (
    ALLOWED_EXTENSIONS, DOC_TYPES, MAX_FILE_SIZE, SINGLE_DOC_TYPES,
)

# Các trường thí sinh được phép tự sửa khi hồ sơ ở trạng thái "Cập nhật thông tin"
EDITABLE_FIELDS = [
    'full_name', 'date_of_birth', 'gender', 'phone', 'email', 'address',
    'school_name', 'graduation_year', 'id_number', 'id_issue_date',
    'id_issue_place', 'vneid_account', 'vneid_level',
]
DATE_FIELDS = ('date_of_birth', 'id_issue_date')


class EautAdmissionPortal(CustomerPortal):

    # =========================================================
    # HELPERS
    # =========================================================

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'admission_count' in counters:
            values['admission_count'] = request.env['eaut.admission.application'].search_count([])
        return values

    def _flash(self, message, level='success'):
        request.session['eaut_admission_flash'] = {'message': message, 'level': level}

    def _pop_flash(self):
        return request.session.pop('eaut_admission_flash', None)

    def _get_application(self, app_id):
        """Hồ sơ phải thuộc về tài khoản đang đăng nhập; trả về record (sudo)."""
        app = request.env['eaut.admission.application'].sudo().browse(app_id).exists()
        if not app or app.partner_id != request.env.user.partner_id:
            raise NotFound()
        return app

    def _get_editable_application(self, app_id):
        app = self._get_application(app_id)
        if app.state != 'draft':
            self._flash(_("Hồ sơ đang được nhà trường xử lý nên không thể chỉnh sửa."), 'danger')
            return app, request.redirect('/my/admission/%s' % app.id)
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

    def _run_safely(self, func):
        """Chạy thao tác ghi trong savepoint để lỗi ràng buộc không làm lưu dữ liệu dở dang."""
        try:
            with request.env.cr.savepoint():
                func()
            return True
        except (ValidationError, UserError) as exc:
            self._flash(exc.args[0] if exc.args else str(exc), 'danger')
            return False

    # =========================================================
    # DANH SÁCH & TẠO HỒ SƠ
    # =========================================================

    @route('/my/admission', type='http', auth='user', website=True)
    def portal_admission_list(self, **kw):
        partner = request.env.user.partner_id
        applications = request.env['eaut.admission.application'].sudo().search(
            [('partner_id', '=', partner.id)]
        )
        available = self._open_campaigns() - applications.campaign_id
        return request.render('eaut_admission.portal_admission_list', {
            'page_name': 'admission',
            'applications': applications,
            'available_campaigns': available,
            'states': dict(STATES),
            'default_phone': partner.phone or '',
            'flash': self._pop_flash(),
        })

    @route('/my/admission/create', type='http', auth='user', website=True, methods=['POST'])
    def portal_admission_create(self, campaign_id=None, phone=None, **kw):
        partner = request.env.user.partner_id
        campaign = request.env['eaut.crm.admission.campaign'].sudo().browse(int(campaign_id or 0)).exists()
        if not campaign or campaign not in self._open_campaigns():
            self._flash(_("Chiến dịch tuyển sinh không còn mở nhận hồ sơ."), 'danger')
            return request.redirect('/my/admission')

        existing = request.env['eaut.admission.application'].sudo().search([
            ('partner_id', '=', partner.id), ('campaign_id', '=', campaign.id),
        ], limit=1)
        if existing:
            return request.redirect('/my/admission/%s' % existing.id)

        created = {}

        def _create():
            created['app'] = request.env['eaut.admission.application'].sudo().create({
                'partner_id': partner.id,
                'campaign_id': campaign.id,
                'full_name': partner.name,
                'email': partner.email,
                'phone': phone or partner.phone,
            })

        if not self._run_safely(_create):
            return request.redirect('/my/admission')
        return request.redirect('/my/admission/%s' % created['app'].id)

    # =========================================================
    # CHI TIẾT HỒ SƠ
    # =========================================================

    @route('/my/admission/<int:app_id>', type='http', auth='user', website=True)
    def portal_admission_detail(self, app_id, **kw):
        app = self._get_application(app_id)
        env = request.env
        step_keys = [key for key, _label in STATES]
        return request.render('eaut_admission.portal_admission_detail', {
            'page_name': 'admission',
            'app': app,
            'editable': app.state == 'draft',
            'steps': STATES,
            'current_step': step_keys.index(app.state),
            'missing': app._get_missing_items(),
            'programs': env['eaut.crm.admission.program'].sudo().search([('active', '=', True)]),
            'methods': env['eaut.crm.admission.method'].sudo().search([('active', '=', True)]),
            'combinations': env['eaut.crm.admission.combination'].sudo().search([('active', '=', True)]),
            'doc_types': DOC_TYPES,
            'single_doc_types': SINGLE_DOC_TYPES,
            'allowed_extensions': ','.join(ALLOWED_EXTENSIONS),
            'max_choices': app.MAX_CHOICES,
            'max_file_mb': MAX_FILE_SIZE // (1024 * 1024),
            'flash': self._pop_flash(),
        })

    @route('/my/admission/<int:app_id>/save', type='http', auth='user', website=True, methods=['POST'])
    def portal_admission_save(self, app_id, **post):
        app, redirect = self._get_editable_application(app_id)
        if redirect:
            return redirect
        vals = {}
        for fname in EDITABLE_FIELDS:
            if fname not in post:
                continue
            value = (post[fname] or '').strip()
            if fname == 'graduation_year':
                if value and not value.isdigit():
                    self._flash(_("Năm tốt nghiệp phải là số."), 'danger')
                    return request.redirect('/my/admission/%s' % app.id)
                value = int(value) if value else 0
            elif fname in DATE_FIELDS:
                try:
                    value = fields.Date.to_date(value) if value else False
                except ValueError:
                    self._flash(_("Ngày nhập không hợp lệ."), 'danger')
                    return request.redirect('/my/admission/%s' % app.id)
            else:
                value = value or False
            vals[fname] = value
        if self._run_safely(lambda: app.write(vals)):
            self._flash(_("Đã lưu thông tin."))
        return request.redirect('/my/admission/%s' % app.id)

    # =========================================================
    # NGUYỆN VỌNG
    # =========================================================

    @route('/my/admission/<int:app_id>/choice/add', type='http', auth='user', website=True, methods=['POST'])
    def portal_admission_choice_add(self, app_id, program_id=None, method_id=None,
                                    combination_id=None, score=None, **kw):
        app, redirect = self._get_editable_application(app_id)
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
            return request.redirect('/my/admission/%s' % app.id)
        try:
            score_value = float((score or '0').replace(',', '.') or 0)
        except ValueError:
            self._flash(_("Điểm không hợp lệ."), 'danger')
            return request.redirect('/my/admission/%s' % app.id)
        if len(app.choice_ids) >= app.MAX_CHOICES:
            self._flash(_("Chỉ được đăng ký tối đa %s nguyện vọng.") % app.MAX_CHOICES, 'danger')
            return request.redirect('/my/admission/%s' % app.id)

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
        return request.redirect('/my/admission/%s' % app.id)

    @route('/my/admission/<int:app_id>/choice/<int:choice_id>/delete', type='http',
           auth='user', website=True, methods=['POST'])
    def portal_admission_choice_delete(self, app_id, choice_id, **kw):
        app, redirect = self._get_editable_application(app_id)
        if redirect:
            return redirect
        app.choice_ids.filtered(lambda c: c.id == choice_id).unlink()
        # Đánh lại thứ tự nguyện vọng cho liên tục
        for index, choice in enumerate(app.choice_ids.sorted('priority'), start=1):
            if choice.priority != index:
                choice.priority = index
        self._flash(_("Đã xóa nguyện vọng."))
        return request.redirect('/my/admission/%s' % app.id)

    # =========================================================
    # TÀI LIỆU
    # =========================================================

    @route('/my/admission/<int:app_id>/upload', type='http', auth='user', website=True, methods=['POST'])
    def portal_admission_upload(self, app_id, doc_type=None, **post):
        app, redirect = self._get_editable_application(app_id)
        if redirect:
            return redirect
        back = '/my/admission/%s' % app.id
        upload = request.httprequest.files.get('file')
        if doc_type not in dict(DOC_TYPES) or not upload or not upload.filename:
            self._flash(_("Vui lòng chọn loại giấy tờ và tệp cần tải lên."), 'danger')
            return request.redirect(back)
        filename = os.path.basename(upload.filename)
        if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
            self._flash(_("Chỉ chấp nhận tệp: %s") % ', '.join(ALLOWED_EXTENSIONS), 'danger')
            return request.redirect(back)
        data = upload.read(MAX_FILE_SIZE + 1)
        if len(data) > MAX_FILE_SIZE:
            self._flash(_("Tệp vượt quá dung lượng tối đa %s MB.") % (MAX_FILE_SIZE // (1024 * 1024)), 'danger')
            return request.redirect(back)
        if not data:
            self._flash(_("Tệp tải lên rỗng."), 'danger')
            return request.redirect(back)

        def _upload():
            if doc_type in SINGLE_DOC_TYPES:
                app.document_ids.filtered(lambda d: d.doc_type == doc_type).unlink()
            request.env['eaut.admission.document'].sudo().create({
                'application_id': app.id,
                'doc_type': doc_type,
                'file': base64.b64encode(data),
                'file_name': filename,
            })

        if self._run_safely(_upload):
            self._flash(_("Đã tải lên tệp %s.") % filename)
        return request.redirect(back)

    @route('/my/admission/<int:app_id>/document/<int:doc_id>/delete', type='http',
           auth='user', website=True, methods=['POST'])
    def portal_admission_document_delete(self, app_id, doc_id, **kw):
        app, redirect = self._get_editable_application(app_id)
        if redirect:
            return redirect
        app.document_ids.filtered(lambda d: d.id == doc_id).unlink()
        self._flash(_("Đã xóa tệp."))
        return request.redirect('/my/admission/%s' % app.id)

    @route('/my/admission/<int:app_id>/document/<int:doc_id>/download', type='http',
           auth='user', website=True)
    def portal_admission_document_download(self, app_id, doc_id, **kw):
        app = self._get_application(app_id)
        doc = app.document_ids.filtered(lambda d: d.id == doc_id)
        if not doc:
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(doc, 'file', 'file_name')
        return stream.get_response(as_attachment=True)

    # =========================================================
    # NỘP HỒ SƠ & GIẤY XÁC NHẬN NHẬP HỌC
    # =========================================================

    @route('/my/admission/<int:app_id>/submit', type='http', auth='user', website=True, methods=['POST'])
    def portal_admission_submit(self, app_id, **kw):
        app, redirect = self._get_editable_application(app_id)
        if redirect:
            return redirect
        if self._run_safely(app.action_submit):
            self._flash(_("Hồ sơ đã hoàn thành và được gửi tới nhà trường. Vui lòng chờ kiểm tra."))
        return request.redirect('/my/admission/%s' % app.id)

    @route('/my/admission/<int:app_id>/letter', type='http', auth='user', website=True)
    def portal_admission_letter(self, app_id, **kw):
        app = self._get_application(app_id)
        if not app.admission_letter_available:
            self._flash(
                _("Giấy xác nhận nhập học chỉ được cấp khi bạn đã đóng học phí và đỗ tốt nghiệp."), 'danger')
            return request.redirect('/my/admission/%s' % app.id)
        pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'eaut_admission.action_report_admission_letter', [app.id])
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', 'attachment; filename="Giay-xac-nhan-nhap-hoc-%s.pdf"' % app.name),
        ]
        return request.make_response(pdf, headers=headers)
