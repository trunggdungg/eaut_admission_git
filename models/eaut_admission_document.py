import os

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

DOC_TYPES = [
    ('transcript', 'Học bạ'),
    ('id_front', 'Căn cước công dân (mặt trước)'),
    ('id_back', 'Căn cước công dân (mặt sau)'),
    ('vneid', 'Thông tin VNeID'),
    ('portrait', 'Ảnh chân dung'),
    ('priority', 'Giấy tờ ưu tiên'),
    ('other', 'Giấy tờ khác'),
]

# Các loại giấy tờ bắt buộc phải có trước khi hoàn thành hồ sơ
REQUIRED_DOC_TYPES = ['transcript', 'id_front', 'id_back', 'vneid']
# Các loại chỉ cho phép 1 tệp (upload lại sẽ thay thế tệp cũ)
SINGLE_DOC_TYPES = ['id_front', 'id_back', 'vneid', 'portrait']
ALLOWED_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png')
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class EautAdmissionDocument(models.Model):
    _name = 'eaut.admission.document'
    _description = 'Tài liệu hồ sơ xét tuyển'
    _order = 'application_id, doc_type, id'

    application_id = fields.Many2one(
        'eaut.admission.application',
        string='Hồ sơ',
        required=True,
        ondelete='cascade',
        index=True,
    )
    doc_type = fields.Selection(DOC_TYPES, string='Loại giấy tờ', required=True)
    file = fields.Binary(string='Tệp', attachment=True, required=True)
    file_name = fields.Char(string='Tên tệp')
    check_state = fields.Selection(
        [
            ('pending', 'Chờ kiểm tra'),
            ('valid', 'Hợp lệ'),
            ('invalid', 'Không hợp lệ'),
        ],
        string='Kết quả kiểm tra',
        default='pending',
        required=True,
    )
    check_note = fields.Char(string='Ghi chú kiểm tra')

    @api.constrains('file_name')
    def _check_file_extension(self):
        for rec in self:
            ext = os.path.splitext(rec.file_name or '')[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValidationError(
                    _("Chỉ chấp nhận tệp định dạng: %s") % ', '.join(ALLOWED_EXTENSIONS)
                )