# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EautAdmissionChoice(models.Model):
    _name = 'eaut.admission.choice'
    _description = 'Nguyện vọng xét tuyển'
    _order = 'application_id, priority, id'

    application_id = fields.Many2one(
        'eaut.admission.application',
        string='Hồ sơ',
        required=True,
        ondelete='cascade',
        index=True,
    )
    priority = fields.Integer(string='Nguyện vọng', default=1, required=True)
    program_id = fields.Many2one(
        'eaut.crm.admission.program',
        string='Ngành xét tuyển',
        required=True,
        ondelete='restrict',
    )
    method_id = fields.Many2one(
        'eaut.crm.admission.method',
        string='Phương thức xét tuyển',
        required=True,
        ondelete='restrict',
    )
    combination_id = fields.Many2one(
        'eaut.crm.admission.combination',
        string='Tổ hợp xét tuyển',
        ondelete='restrict',
    )
    score = fields.Float(string='Điểm thí sinh khai', digits=(3, 2))
    verified_score = fields.Float(
        string='Điểm đã kiểm tra',
        digits=(3, 2),
        help='Điểm do phòng đào tạo xác minh từ học bạ; dùng làm điểm xét tuyển nếu có.',
    )
    registration_id = fields.Many2one(
        'eaut.crm.registration',
        string='Đơn xét tuyển CRM',
        copy=False,
        readonly=True,
        ondelete='set null',
    )

    @api.constrains('score', 'verified_score')
    def _check_scores(self):
        for rec in self:
            if not (0 <= rec.score <= 30) or not (0 <= rec.verified_score <= 30):
                raise ValidationError(_("Điểm phải nằm trong khoảng từ 0 đến 30."))

    @api.constrains('application_id', 'program_id', 'method_id', 'combination_id')
    def _check_duplicate_choice(self):
        for rec in self:
            duplicate = self.search_count([
                ('id', '!=', rec.id),
                ('application_id', '=', rec.application_id.id),
                ('program_id', '=', rec.program_id.id),
                ('method_id', '=', rec.method_id.id),
                ('combination_id', '=', rec.combination_id.id),
            ])
            if duplicate:
                raise ValidationError(
                    _("Nguyện vọng ngành %(program)s với cùng phương thức/tổ hợp đã có trong hồ sơ.",
                      program=rec.program_id.display_name)
                )

    @api.constrains('application_id')
    def _check_max_choices(self):
        limit = self.env['eaut.admission.application'].MAX_CHOICES
        for rec in self:
            if len(rec.application_id.choice_ids) > limit:
                raise ValidationError(
                    _("Mỗi hồ sơ chỉ được đăng ký tối đa %s nguyện vọng.") % limit
                )

    def unlink(self):
        registrations = self.registration_id
        res = super().unlink()
        registrations.sudo().unlink()
        return res
