# -*- coding: utf-8 -*-
from odoo import fields, models


class EautAdmissionChoice(models.Model):
    _name = 'eaut.admission.choice'
    _description = 'Nguyện vọng xét tuyển'
    _order = 'application_id, priority, id'

    application_id = fields.Many2one(
        'eaut.admission.application', string='Hồ sơ', required=True, ondelete='cascade', index=True)
    priority = fields.Integer(string='Nguyện vọng', default=1)
    program_id = fields.Many2one(
        'eaut.crm.admission.program', string='Ngành xét tuyển', required=True, ondelete='restrict')
    method_id = fields.Many2one(
        'eaut.crm.admission.method', string='Phương thức xét tuyển', required=True, ondelete='restrict')
    combination_id = fields.Many2one(
        'eaut.crm.admission.combination', string='Tổ hợp xét tuyển', ondelete='restrict')
