from odoo import api, fields, models

SUBMIT_TYPES = [
    ('new', 'Gửi lần đầu (tạo hồ sơ)'),
    ('duplicate', 'Gửi lại form (đã có hồ sơ)'),
    ('resubmit', 'Nộp lại sau khi bổ sung'),
]


class EautAdmissionSubmission(models.Model):
    _name = 'eaut.admission.submission'
    _description = 'Lượt gửi form tuyển sinh'
    _order = 'application_id, number desc, id desc'

    application_id = fields.Many2one(
        'eaut.admission.application',
        string='Hồ sơ',
        required=True,
        ondelete='cascade',
        index=True,
    )
    number = fields.Integer(string='Lần gửi', readonly=True)
    name = fields.Char(string='Lượt gửi', compute='_compute_name', store=True)
    submit_type = fields.Selection(SUBMIT_TYPES, string='Loại lượt gửi', required=True, readonly=True)
    submitted_at = fields.Datetime(string='Thời điểm gửi', default=fields.Datetime.now, readonly=True)
    form_id = fields.Many2one(
        'eaut.crm.admission.campaign.form',
        string='Form tuyển sinh',
        readonly=True,
        ondelete='set null',
    )
    full_name = fields.Char(string='Họ tên đã nhập', readonly=True)
    phone = fields.Char(string='SĐT đã nhập', readonly=True)
    email = fields.Char(string='Email đã nhập', readonly=True)
    email_differs = fields.Boolean(
        string='Email khác hồ sơ',
        compute='_compute_email_differs',
        store=True,
        help='Email của lượt gửi này khác email đang lưu trong hồ sơ.',
    )
    ip_address = fields.Char(string='Địa chỉ IP', readonly=True)
    summary = fields.Text(string='Thông tin đã gửi', readonly=True)

    @api.depends('number')
    def _compute_name(self):
        for rec in self:
            rec.name = 'Lần %s' % (rec.number or '?')

    @api.depends('email', 'application_id.email')
    def _compute_email_differs(self):
        for rec in self:
            sent = (rec.email or '').strip().lower()
            current = (rec.application_id.email or '').strip().lower()
            rec.email_differs = bool(sent and current and sent != current)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('number'):
                last = self.search(
                    [('application_id', '=', vals.get('application_id'))],
                    order='number desc', limit=1,
                )
                vals['number'] = (last.number or 0) + 1
        return super().create(vals_list)