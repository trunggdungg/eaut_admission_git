# -*- coding: utf-8 -*-
import re

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eaut_admission_document import DOC_TYPES, REQUIRED_DOC_TYPES

STATES = [
    ('draft', 'Cập nhật thông tin'),
    ('completed', 'Hoàn thành hồ sơ'),
    ('reviewing', 'Đang kiểm tra'),
    ('done', 'Đã hoàn thành'),
]

# Các trường thông tin cá nhân thí sinh tự nhập trên form
PERSONAL_FIELDS = [
    'full_name', 'date_of_birth', 'gender', 'phone', 'email', 'address',
    'school_name', 'graduation_year', 'id_number', 'id_issue_date',
    'id_issue_place', 'vneid_account', 'vneid_level',
]

ACCEPTED_MESSAGE = (
    "Bạn đã được nhà trường chấp nhận hồ sơ. Bạn có thể đóng học phí để nhận "
    "giấy xác nhận nhập học, với điều kiện phải đỗ tốt nghiệp THPT."
)


class EautAdmissionApplication(models.Model):
    _name = 'eaut.admission.application'
    _description = 'Hồ sơ xét tuyển'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'id desc'

    MAX_CHOICES = 5

    name = fields.Char(string='Mã hồ sơ', default='New', copy=False, readonly=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    partner_id = fields.Many2one(
        'res.partner',
        string='Liên hệ thí sinh',
        index=True,
        ondelete='restrict',
        tracking=True,
        help='Tự tạo theo email khi thí sinh nộp hồ sơ; dùng để gửi thông báo và nhận trao đổi.',
    )
    campaign_id = fields.Many2one(
        'eaut.crm.admission.campaign',
        string='Chiến dịch tuyển sinh',
        required=True,
        tracking=True,
        ondelete='restrict',
        domain=[('active', '=', True)],
    )
    campaign_form_id = fields.Many2one(
        'eaut.crm.admission.campaign.form',
        string='Form tuyển sinh',
        ondelete='restrict',
        copy=False,
        help='Form mà thí sinh đã dùng để nộp hồ sơ; quyết định nguồn Lead.',
    )
    lead_id = fields.Many2one(
        'eaut.crm.lead',
        string='Lead CRM',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    state = fields.Selection(
        STATES,
        string='Trạng thái',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )

    # ---------------- Thông tin cá nhân ----------------
    full_name = fields.Char(string='Họ và tên', tracking=True)
    date_of_birth = fields.Date(string='Ngày sinh')
    gender = fields.Selection(
        [('male', 'Nam'), ('female', 'Nữ'), ('other', 'Khác')],
        string='Giới tính',
    )
    phone = fields.Char(string='Số điện thoại', tracking=True)
    email = fields.Char(string='Email')
    address = fields.Text(string='Địa chỉ liên hệ')
    school_name = fields.Char(string='Trường THPT')
    graduation_year = fields.Integer(string='Năm tốt nghiệp THPT')

    # ---------------- Căn cước & VNeID ----------------
    id_number = fields.Char(string='Số căn cước công dân', tracking=True)
    id_issue_date = fields.Date(string='Ngày cấp')
    id_issue_place = fields.Char(string='Nơi cấp')
    vneid_account = fields.Char(
        string='Tài khoản VNeID',
        help='Số định danh cá nhân dùng đăng nhập VNeID.',
    )
    vneid_level = fields.Selection(
        [('1', 'Mức 1'), ('2', 'Mức 2')],
        string='Mức định danh điện tử',
    )
    vneid_verified = fields.Boolean(string='Đã xác minh VNeID', tracking=True)

    # ---------------- Nguyện vọng & tài liệu ----------------
    choice_ids = fields.One2many('eaut.admission.choice', 'application_id', string='Nguyện vọng')
    document_ids = fields.One2many('eaut.admission.document', 'application_id', string='Tài liệu')
    registration_ids = fields.One2many(
        'eaut.crm.registration', 'application_id', string='Đơn xét tuyển CRM', readonly=True,
    )
    submission_ids = fields.One2many(
        'eaut.admission.submission', 'application_id', string='Lượt gửi form', readonly=True,
    )
    submission_count = fields.Integer(string='Số lần gửi form', compute='_compute_submission_count')
    registration_count = fields.Integer(compute='_compute_registration_count')
    missing_items = fields.Text(string='Còn thiếu', compute='_compute_missing_items')
    is_complete = fields.Boolean(string='Đủ điều kiện nộp', compute='_compute_missing_items')

    # ---------------- Xử lý hồ sơ ----------------
    submitted_date = fields.Datetime(string='Ngày hoàn thành hồ sơ', readonly=True, copy=False)
    review_date = fields.Datetime(string='Ngày bắt đầu kiểm tra', readonly=True, copy=False)
    done_date = fields.Datetime(string='Ngày có kết quả', readonly=True, copy=False)
    reviewer_id = fields.Many2one('res.users', string='Cán bộ kiểm tra', tracking=True, copy=False)
    supplement_request = fields.Text(
        string='Nội dung yêu cầu bổ sung',
        copy=False,
        help='Thí sinh nhìn thấy nội dung này trên portal khi hồ sơ bị trả về để bổ sung.',
    )
    result = fields.Selection(
        [('accepted', 'Chấp nhận hồ sơ'), ('rejected', 'Không chấp nhận')],
        string='Kết quả',
        tracking=True,
        copy=False,
    )
    result_message = fields.Text(string='Thông báo kết quả gửi thí sinh', copy=False)
    internal_note = fields.Html(string='Ghi chú nội bộ')

    # ---------------- Học phí & giấy xác nhận nhập học ----------------
    tuition_amount = fields.Monetary(string='Học phí cần đóng', currency_field='currency_id', tracking=True)
    payment_state = fields.Selection(
        [('unpaid', 'Chưa đóng'), ('paid', 'Đã đóng')],
        string='Học phí',
        default='unpaid',
        tracking=True,
        copy=False,
    )
    payment_date = fields.Date(string='Ngày đóng học phí', copy=False)
    payment_reference = fields.Char(string='Mã giao dịch / biên lai', copy=False)
    graduation_status = fields.Selection(
        [('pending', 'Chờ kết quả tốt nghiệp'), ('passed', 'Đã đỗ tốt nghiệp'), ('failed', 'Chưa đỗ tốt nghiệp')],
        string='Tốt nghiệp THPT',
        default='pending',
        tracking=True,
        copy=False,
    )
    admission_letter_available = fields.Boolean(
        string='Được cấp giấy xác nhận nhập học',
        compute='_compute_admission_letter_available',
    )

    _phone_campaign_unique = models.Constraint(
        'unique(phone, campaign_id)',
        'Số điện thoại này đã có hồ sơ trong chiến dịch tuyển sinh!',
    )

    # =========================================================
    # COMPUTE
    # =========================================================

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/admission/%s' % rec.id

    def _get_tracking_url(self):
        """Link theo dõi đầy đủ (kèm token) gửi cho thí sinh qua email."""
        self.ensure_one()
        rec = self.sudo()
        return rec.get_base_url() + rec.get_portal_url()

    @api.depends(
        'full_name', 'date_of_birth', 'gender', 'phone', 'email', 'address', 'school_name',
        'graduation_year', 'id_number', 'id_issue_date', 'id_issue_place', 'vneid_account',
        'choice_ids', 'document_ids.doc_type',
    )
    def _compute_missing_items(self):
        for rec in self:
            items = rec._get_missing_items()
            rec.missing_items = '\n'.join(items)
            rec.is_complete = not items

    @api.depends('submission_ids')
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    @api.depends('registration_ids')
    def _compute_registration_count(self):
        for rec in self:
            rec.registration_count = len(rec.registration_ids)

    @api.depends('result', 'payment_state', 'graduation_status')
    def _compute_admission_letter_available(self):
        for rec in self:
            rec.admission_letter_available = (
                rec.result == 'accepted'
                and rec.payment_state == 'paid'
                and rec.graduation_status == 'passed'
            )

    def _get_missing_items(self):
        """Danh sách các mục thí sinh còn phải bổ sung trước khi hoàn thành hồ sơ."""
        self.ensure_one()
        required_fields = [
            'full_name', 'date_of_birth', 'gender', 'phone', 'email', 'address',
            'school_name', 'graduation_year', 'id_number', 'id_issue_date',
            'id_issue_place', 'vneid_account',
        ]
        missing = [
            _("Chưa nhập: %s") % self._fields[fname].string
            for fname in required_fields if not self[fname]
        ]
        if not self.choice_ids:
            missing.append(_("Chưa chọn nguyện vọng xét tuyển (ngành học)."))
        doc_labels = dict(DOC_TYPES)
        uploaded = set(self.document_ids.mapped('doc_type'))
        missing += [
            _("Chưa tải lên: %s") % doc_labels[dtype]
            for dtype in REQUIRED_DOC_TYPES if dtype not in uploaded
        ]
        return missing

    # =========================================================
    # VALIDATION
    # =========================================================

    @api.constrains('phone')
    def _check_phone(self):
        for rec in self:
            if rec.phone and not re.fullmatch(r'0\d{9}', rec.phone):
                raise ValidationError(
                    _("Số điện thoại '%s' phải gồm đúng 10 chữ số và bắt đầu bằng số 0.") % rec.phone
                )

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

    @api.constrains('graduation_year')
    def _check_graduation_year(self):
        this_year = fields.Date.today().year
        for rec in self:
            if rec.graduation_year and not (this_year - 10 <= rec.graduation_year <= this_year + 1):
                raise ValidationError(_("Năm tốt nghiệp THPT không hợp lệ."))

    @api.constrains('date_of_birth', 'id_issue_date')
    def _check_dates(self):
        today = fields.Date.today()
        for rec in self:
            if rec.date_of_birth and rec.date_of_birth >= today:
                raise ValidationError(_("Ngày sinh phải nhỏ hơn ngày hiện tại."))
            if rec.id_issue_date and rec.id_issue_date > today:
                raise ValidationError(_("Ngày cấp căn cước không được ở tương lai."))
            if rec.date_of_birth and rec.id_issue_date and rec.id_issue_date < rec.date_of_birth:
                raise ValidationError(_("Ngày cấp căn cước phải sau ngày sinh."))

    # =========================================================
    # CRUD
    # =========================================================

    @api.model
    def _normalize_vals(self, vals):
        if vals.get('phone'):
            vals['phone'] = self.env['eaut.crm.lead']._normalize_phone(vals['phone'])
        if vals.get('email'):
            vals['email'] = vals['email'].strip().lower()
        for fname in ('full_name', 'id_number', 'id_issue_place', 'vneid_account', 'school_name'):
            if vals.get(fname):
                vals[fname] = vals[fname].strip()
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_vals(vals)
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('eaut.admission.application') or 'New'
        records = super().create(vals_list)
        for rec in records.sudo():
            rec._ensure_partner()
            rec._portal_ensure_token()
            rec._subscribe_staff(rec.campaign_id.sale_team_id.leader_id)
        records._ensure_lead()
        return records

    def write(self, vals):
        self._normalize_vals(vals)
        res = super().write(vals)
        if 'phone' in vals:
            # Đổi SĐT: gỡ liên kết lead cũ rồi tìm/tạo lead theo SĐT mới
            self.filtered(lambda a: a.lead_id and a.lead_id.phone != a.phone).write({'lead_id': False})
            self._ensure_lead()
        return res

    # =========================================================
    # LIÊN KẾT VỚI CRM
    # =========================================================

    def _ensure_partner(self):
        """Gắn liên hệ (res.partner) theo email; chưa có thì tạo mới. Không ghi đè liên hệ cũ."""
        Partner = self.env['res.partner'].sudo()
        for rec in self.filtered(lambda a: not a.partner_id and a.email):
            partner = Partner.search([('email', '=ilike', rec.email)], limit=1)
            if not partner:
                partner = Partner.create({
                    'name': rec.full_name or rec.email,
                    'email': rec.email,
                    'phone': rec.phone,
                })
            rec.partner_id = partner

    def _subscribe_staff(self, users):
        """Cán bộ theo dõi hồ sơ để nhận thông báo khi thí sinh trao đổi trên portal."""
        partners = users.partner_id
        if partners:
            self.message_subscribe(partner_ids=partners.ids)

    def _ensure_lead(self):
        """Tìm Lead theo SĐT (chưa có thì tạo) để phòng tuyển sinh theo dõi trong CRM."""
        Lead = self.env['eaut.crm.lead'].sudo()
        portal_source = self.env.ref('eaut_admission.crm_source_portal', raise_if_not_found=False)
        for rec in self.sudo().filtered(lambda a: not a.lead_id and a.phone):
            source = rec.campaign_form_id.default_source_id or portal_source
            lead = Lead.search([('phone', '=', rec.phone)], limit=1)
            if not lead:
                vals = {
                    'name': rec.full_name or rec.partner_id.name or _('Chưa xác định'),
                    'phone': rec.phone,
                    'email': rec.email or False,
                    'campaign_id': rec.campaign_id.id,
                }
                if source:
                    vals['source_id'] = source.id
                lead = Lead.create(vals)
            rec.lead_id = lead

    def _sync_lead_info(self):
        """Bổ sung các thông tin còn trống của Lead từ hồ sơ (không ghi đè dữ liệu cũ)."""
        for rec in self.sudo().filtered('lead_id'):
            lead = rec.lead_id
            vals = {}
            for lead_field, app_field in (
                ('email', 'email'), ('date_of_birth', 'date_of_birth'), ('gender', 'gender'),
                ('address', 'address'), ('school_name', 'school_name'),
                ('graduation_year', 'graduation_year'),
            ):
                if rec[app_field] and not lead[lead_field]:
                    vals[lead_field] = rec[app_field]
            if vals:
                lead.write(vals)

    def _sync_registrations(self):
        """Mỗi nguyện vọng tương ứng 1 đơn xét tuyển (eaut.crm.registration) trong CRM."""
        Registration = self.env['eaut.crm.registration'].sudo()
        for rec in self.sudo().filtered('lead_id'):
            form = rec.campaign_form_id or rec.campaign_id.admission_form_ids.filtered('active')[:1]
            for choice in rec.choice_ids:
                vals = {
                    'lead_id': rec.lead_id.id,
                    'application_id': rec.id,
                    'admission_program_id': choice.program_id.id,
                    'admission_method_id': choice.method_id.id,
                    'admission_combination_id': choice.combination_id.id,
                    'score': choice.verified_score or choice.score,
                    'campaign_form_id': form.id or False,
                    'form_lead_name': rec.full_name,
                    'form_lead_email': rec.email,
                    'form_lead_phone': rec.phone,
                }
                if choice.registration_id:
                    choice.registration_id.write(vals)
                else:
                    choice.registration_id = Registration.create(vals)

    def _sync_lead_stage(self, flag):
        """Chuyển Lead sang giai đoạn chốt (is_won) / mất (is_lost) nếu CRM có cấu hình."""
        Stage = self.env['eaut.crm.stage'].sudo()
        stage = Stage.search([(flag, '=', True)], order='sequence, id', limit=1)
        if stage:
            self.sudo().mapped('lead_id').write({'stage_id': stage.id})

    # =========================================================
    # ACTIONS (chuyển trạng thái)
    # =========================================================

    def _check_state(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("Hồ sơ %(name)s đang ở trạng thái '%(state)s' nên không thực hiện được thao tác này.",
                      name=rec.name, state=dict(STATES)[rec.state])
                )

    def _notify_student(self, title, text):
        """Gửi thông báo (chatter + email) tới tài khoản thí sinh."""
        self.ensure_one()
        lines = Markup('<br/>').join((text or '').splitlines())
        self.message_post(
            body=Markup('<p>%s</p><p>%s</p>') % (title, lines),
            partner_ids=self.partner_id.ids,
            subtype_xmlid='mail.mt_comment',
        )

    def action_submit(self):
        """Thí sinh bấm 'Hoàn thành hồ sơ': kiểm tra đủ thông tin rồi chuyển sang chờ kiểm tra."""
        self._check_state(['draft'])
        for rec in self:
            missing = rec._get_missing_items()
            if missing:
                raise UserError(
                    _("Hồ sơ chưa đủ điều kiện nộp:\n%s") % '\n'.join('- ' + m for m in missing)
                )
        self.write({
            'state': 'completed',
            'submitted_date': fields.Datetime.now(),
            'supplement_request': False,
        })
        self._ensure_lead()
        self._sync_lead_info()
        self._sync_registrations()
        self._send_tracking_email()

    def _format_submission_value(self, fname, value):
        field = self._fields[fname]
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, value)
        return str(value)

    def _build_submission_summary(self, vals, choices, documents):
        """Nội dung form đã gửi ở dạng văn bản dễ đọc, để cán bộ đối chiếu giữa các lượt gửi."""
        env = self.env
        lines = [
            '%s: %s' % (self._fields[fname].string, self._format_submission_value(fname, vals[fname]))
            for fname in PERSONAL_FIELDS if vals.get(fname)
        ]
        for choice in choices or []:
            program = env['eaut.crm.admission.program'].sudo().browse(choice['program_id'])
            method = env['eaut.crm.admission.method'].sudo().browse(choice['method_id'])
            combination = env['eaut.crm.admission.combination'].sudo().browse(choice.get('combination_id') or 0)
            lines.append('Nguyện vọng %s: %s - %s - %s - điểm %s' % (
                choice.get('priority'), program.display_name, method.display_name,
                combination.display_name or '-', choice.get('score') or 0))
        doc_labels = dict(DOC_TYPES)
        for doc in documents or []:
            lines.append('Tệp [%s]: %s' % (doc_labels.get(doc['doc_type']), doc['file_name']))
        return '\n'.join(lines)

    def _log_submission(self, submit_type, form=None, vals=None, choices=None, documents=None, ip=None):
        """Ghi lại 1 lượt gửi form. Không truyền vals thì lấy nội dung hiện tại của hồ sơ."""
        self.ensure_one()
        if vals is None:
            vals = {fname: self[fname] for fname in PERSONAL_FIELDS}
            choices = [{
                'priority': c.priority, 'program_id': c.program_id.id, 'method_id': c.method_id.id,
                'combination_id': c.combination_id.id, 'score': c.score,
            } for c in self.choice_ids.sorted('priority')]
            documents = [{'doc_type': d.doc_type, 'file_name': d.file_name} for d in self.document_ids]
        return self.env['eaut.admission.submission'].sudo().create({
            'application_id': self.id,
            'submit_type': submit_type,
            'form_id': (form or self.campaign_form_id).id,
            'full_name': vals.get('full_name'),
            'phone': vals.get('phone'),
            'email': vals.get('email'),
            'ip_address': ip,
            'summary': self._build_submission_summary(vals, choices, documents),
        })

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lượt gửi form'),
            'res_model': 'eaut.admission.submission',
            'view_mode': 'list,form',
            'domain': [('application_id', '=', self.id)],
        }

    def _send_tracking_email(self):
        """Email xác nhận đã nhận hồ sơ, kèm nút 'Theo dõi hồ sơ' (link có token)."""
        template = self.env.ref('eaut_admission.mail_template_application_received', raise_if_not_found=False)
        if not template:
            return
        for rec in self.sudo().filtered('email'):
            template.sudo().send_mail(rec.id, force_send=True, email_layout_xmlid='mail.mail_notification_light')

    def action_send_tracking_email(self):
        """Gửi lại email theo dõi (khi thí sinh làm mất email hoặc nhập sai email)."""
        for rec in self:
            if not rec.email:
                raise UserError(_("Hồ sơ %s chưa có email thí sinh.") % rec.name)
        self._send_tracking_email()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'message': _("Đã gửi email theo dõi hồ sơ."), 'type': 'success', 'sticky': False},
        }

    def action_start_review(self):
        self._check_state(['completed'])
        self.write({
            'state': 'reviewing',
            'review_date': fields.Datetime.now(),
            'reviewer_id': self.env.user.id,
        })
        self._subscribe_staff(self.env.user)

    def action_request_supplement(self):
        """Trả hồ sơ về cho thí sinh bổ sung; bắt buộc ghi rõ nội dung cần bổ sung."""
        self._check_state(['completed', 'reviewing'])
        for rec in self:
            if not (rec.supplement_request or '').strip():
                raise UserError(_("Vui lòng nhập 'Nội dung yêu cầu bổ sung' trước khi trả hồ sơ."))
            rec._notify_student(_("Hồ sơ cần bổ sung thông tin:"), rec.supplement_request)
        self.write({'state': 'draft'})

    def action_accept(self):
        self._check_state(['reviewing'])
        today = fields.Date.today()
        for rec in self:
            rec.write({
                'state': 'done',
                'result': 'accepted',
                'result_message': rec.result_message or ACCEPTED_MESSAGE,
                'done_date': fields.Datetime.now(),
            })
            rec.sudo().registration_ids.write({'approved_date': today})
            rec._notify_student(_("Hồ sơ của bạn đã được chấp nhận."), rec.result_message)
        self._sync_lead_stage('is_won')

    def action_reject(self):
        self._check_state(['reviewing'])
        for rec in self:
            if not (rec.result_message or '').strip():
                raise UserError(_("Vui lòng nhập 'Thông báo kết quả gửi thí sinh' (lý do) trước khi từ chối."))
            rec.write({
                'state': 'done',
                'result': 'rejected',
                'done_date': fields.Datetime.now(),
            })
            rec._notify_student(_("Hồ sơ của bạn chưa được chấp nhận."), rec.result_message)
        self._sync_lead_stage('is_lost')

    def action_mark_paid(self):
        self._check_state(['done'])
        for rec in self:
            if rec.result != 'accepted':
                raise UserError(_("Chỉ hồ sơ được chấp nhận mới đóng học phí."))
        self.write({'payment_state': 'paid', 'payment_date': fields.Date.today()})

    def action_confirm_graduation(self):
        self._check_state(['done'])
        self.write({'graduation_status': 'passed'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'result': False, 'done_date': False})

    def action_print_admission_letter(self):
        self.ensure_one()
        if not self.admission_letter_available:
            raise UserError(
                _("Chỉ cấp giấy xác nhận nhập học khi hồ sơ được chấp nhận, đã đóng học phí và đã đỗ tốt nghiệp.")
            )
        return self.env.ref('eaut_admission.action_report_admission_letter').report_action(self)

    def action_view_lead(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead CRM'),
            'res_model': 'eaut.crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
        }

    def action_view_registrations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đơn xét tuyển CRM'),
            'res_model': 'eaut.crm.registration',
            'view_mode': 'list,form',
            'domain': [('application_id', '=', self.id)],
        }
