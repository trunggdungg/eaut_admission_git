# -*- coding: utf-8 -*-
from odoo import fields, models

DOC_TYPES = [
    ('transcript', 'Học bạ'),
    ('id_front', 'Căn cước công dân (mặt trước)'),
    ('id_back', 'Căn cước công dân (mặt sau)'),
    ('vneid', 'Thông tin VNeID'),
    ('other', 'Giấy tờ khác'),
]
# Giấy tờ bắt buộc khi nộp hồ sơ
REQUIRED_DOC_TYPES = ['transcript', 'id_front', 'id_back', 'vneid']
ALLOWED_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png')
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class EautAdmissionDocument(models.Model):
    _name = 'eaut.admission.document'
    _description = 'Tài liệu hồ sơ xét tuyển'
    _order = 'application_id, doc_type, id'

    application_id = fields.Many2one(
        'eaut.admission.application', string='Hồ sơ', required=True, ondelete='cascade', index=True)
    doc_type = fields.Selection(DOC_TYPES, string='Loại giấy tờ', required=True)
    file = fields.Binary(string='Tệp', attachment=True, required=True)
    file_name = fields.Char(string='Tên tệp')
