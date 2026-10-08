# -*- coding: utf-8 -*-

from odoo import _,api, fields, models

class EautAdmission(models.Model):
    _name = 'eaut.admission'
    _description = 'Sample Model'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    date = fields.Date(string='Date')
    active = fields.Boolean(string='Active', default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done')
    ], string='State', default='draft', tracking=True)
    
    def button_action(self):
        pass
    
    @api.model_create_multi
    def create(self, vals):
        """Create records using provided values."""
        res = super().create(vals)
        return res
    
    def write(self, vals):
        """Write records using provided values."""
        res = super().write(vals)
        return res
    
    def unlink(self):
        """Delete records"""
        return super().unlink()