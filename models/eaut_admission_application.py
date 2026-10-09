# -*- coding: utf-8 -*-
import re

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

STATES = [
    ('draft', 'Cập nhật thông tin'),
    ('completed', 'Hoàn thành hồ sơ'),
    ('reviewing', 'Đang kiểm tra'),
    ('done', 'Đã hoàn thành'),
]

# Các trường thông tin cá nhân thí sinh nhập trên form
PERSONAL_FIELDS = [
    'full_name', 'date_of_birth', 'gender', 'phone', 'email', 'address',
    'school_name', 'graduation_year', 'id_number', 'id_issue_date',
    'id_issue_place', 'vneid_account',
]


class EautAdmissionApplication(models.Model):
    _name = 'eaut.admission.application'
    _description = 'Hồ sơ xét tuyển'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'id desc'

    name = fields.Char(string='Mã hồ sơ', default='New', copy=False, readonly=True, index=True)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        STATES, string='Trạng thái', default='completed', required=True, tracking=True, index=True)
    campaign_id = fields.Many2one(
        'eaut.crm.admission.campaign', string='Chiến dịch tuyển sinh', required=True,
        ondelete='restrict', tracking=True)
    campaign_form_id = fields.Many2one(
        'eaut.crm.admission.campaign.form', string='Form tuyển sinh', ondelete='restrict')
    partner_id = fields.Many2one(
        'res.partner', string='Liên hệ thí sinh', ondelete='restrict',
        help='Tự tạo theo email khi thí sinh nộp hồ sơ, dùng để gửi thông báo và nhận trao đổi.')

    full_name = fields.Char(string='Họ và tên', required=True, tracking=True)
    date_of_birth = fields.Date(string='Ngày sinh')
    gender = fields.Selection([('male', 'Nam'), ('female', 'Nữ'), ('other', 'Khác')], string='Giới tính')
    phone = fields.Char(string='Số điện thoại', required=True, tracking=True)
    email = fields.Char(string='Email', required=True)
    address = fields.Text(string='Địa chỉ liên hệ')
    school_name = fields.Char(string='Trường THPT')
    graduation_year = fields.Integer(string='Năm tốt nghiệp THPT')
    id_number = fields.Char(string='Số căn cước công dân')
    id_issue_date = fields.Date(string='Ngày cấp')
    id_issue_place = fields.Char(string='Nơi cấp')
    vneid_account = fields.Char(string='Tài khoản VNeID')

    choice_ids = fields.One2many('eaut.admission.choice', 'application_id', string='Nguyện vọng')
    document_ids = fields.One2many('eaut.admission.document', 'application_id', string='Tài liệu')

    result_message = fields.Text(
        string='Thông báo kết quả gửi thí sinh',
        help='Hiển thị trên trang theo dõi và gửi email cho thí sinh khi hồ sơ chuyển sang "Đã hoàn thành".')
    internal_note = fields.Html(string='Ghi chú nội bộ')

    # =========================================================
    # PORTAL
    # =========================================================

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/admission/%s' % rec.id

    def get_tracking_url(self):
        """Link theo dõi đầy đủ (kèm token) đặt trong email gửi thí sinh."""
        self.ensure_one()
        rec = self.sudo()
        return rec.get_base_url() + rec.get_portal_url()

    # =========================================================
    # VALIDATION
    # =========================================================

    @api.constrains('phone')
    def _check_phone(self):
        for rec in self:
            if rec.phone and not re.fullmatch(r'0\d{9}', rec.phone):
                raise ValidationError(
                    _("Số điện thoại '%s' phải gồm đúng 10 chữ số và bắt đầu bằng số 0.") % rec.phone)

    @api.constrains('email')
    def _check_email(self):
        for rec in self:
            if rec.email and not re.match(r'^[\w\.\-+]+@[\w\.-]+\.\w+$', rec.email):
                raise ValidationError(_("Email '%s' không đúng định dạng!") % rec.email)

    @api.constrains('id_number')
    def _check_id_number(self):
        for rec in self:
            if rec.id_number and not re.fullmatch(r'\d{12}', rec.id_number):
                raise ValidationError(_("Số căn cước công dân phải gồm đúng 12 chữ số."))

    # =========================================================
    # CRUD
    # =========================================================

    @staticmethod
    def _normalize_phone(phone):
        phone = re.sub(r'[^0-9+]', '', (phone or '').strip())
        return '0' + phone[3:] if phone.startswith('+84') else phone

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('phone'):
                vals['phone'] = self._normalize_phone(vals['phone'])
            if vals.get('email'):
                vals['email'] = vals['email'].strip().lower()
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('eaut.admission.application') or 'New'
        records = super().create(vals_list)
        for rec in records.sudo():
            rec._ensure_partner()
            rec._portal_ensure_token()
        return records

    def write(self, vals):
        old_states = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        for rec in self:
            if old_states.get(rec.id) not in (None, rec.state):
                rec._notify_state_change()
        return res

    def _ensure_partner(self):
        """Gắn liên hệ (res.partner) theo email; chưa có thì tạo mới."""
        Partner = self.env['res.partner'].sudo()
        for rec in self.filtered(lambda a: not a.partner_id and a.email):
            partner = Partner.search([('email', '=ilike', rec.email)], limit=1)
            rec.partner_id = partner or Partner.create({
                'name': rec.full_name, 'email': rec.email, 'phone': rec.phone})

    # =========================================================
    # EMAIL
    # =========================================================

    def _send_tracking_email(self):
        """Email xác nhận đã nhận hồ sơ, kèm nút 'Theo dõi hồ sơ'."""
        template = self.env.ref('eaut_admission.mail_template_application_received', raise_if_not_found=False)
        if template:
            for rec in self.sudo().filtered('email'):
                template.sudo().send_mail(
                    rec.id, force_send=True, email_layout_xmlid='mail.mail_notification_light')

    def action_send_tracking_email(self):
        """Gửi lại email theo dõi (thí sinh làm mất email)."""
        self._send_tracking_email()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'message': _("Đã gửi email theo dõi hồ sơ."), 'type': 'success', 'sticky': False},
        }

    def _notify_state_change(self):
        """Khi cán bộ đổi trạng thái: gửi thông báo cho thí sinh (hiện cả ở khung trao đổi)."""
        self.ensure_one()
        body = Markup('<p>%s <b>%s</b></p>') % (
            _("Trạng thái hồ sơ của bạn:"), dict(STATES)[self.state])
        if self.state == 'done' and self.result_message:
            body += Markup('<p>%s</p>') % Markup('<br/>').join(self.result_message.splitlines())
        self.message_post(
            body=body, partner_ids=self.partner_id.ids, subtype_xmlid='mail.mt_comment')
