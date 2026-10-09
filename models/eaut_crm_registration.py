# -*- coding: utf-8 -*-
from odoo import fields, models


class EautCrmRegistration(models.Model):
    _inherit = 'eaut.crm.registration'

    application_id = fields.Many2one(
        'eaut.admission.application',
        string='Hồ sơ portal',
        index=True,
        copy=False,
        ondelete='set null',
        help='Hồ sơ xét tuyển trên cổng portal đã sinh ra đơn xét tuyển này.',
    )
