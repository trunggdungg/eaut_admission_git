# -*- coding: utf-8 -*-
{
    'name': 'Eaut Admission',
    'version': '1.0',
    'summary': 'Thí sinh nộp hồ sơ xét tuyển trên portal, nhận email theo dõi; cán bộ xử lý trong app',
    'description': '''
        - Form công khai trên portal: thí sinh điền thông tin, chọn nguyện vọng, upload học bạ / căn cước / VNeID.
        - Hồ sơ được gửi vào app Hồ sơ tuyển sinh; thí sinh nhận email có nút "Theo dõi hồ sơ".
        - Trang theo dõi (kiểu Helpdesk): xem thông tin đã nộp, trạng thái, kết quả và trao đổi với nhà trường.
        - Trạng thái: Cập nhật thông tin -> Hoàn thành hồ sơ -> Đang kiểm tra -> Đã hoàn thành.
    ''',
    'category': 'Services',
    'author': 'EAUT',
    'depends': ['base', 'mail', 'portal', 'eaut_crm'],
    'data': [
        'security/eaut_admission_groups.xml',
        'security/ir.model.access.csv',
        'data/eaut_admission_data.xml',
        'views/eaut_admission_application_views.xml',
        'views/eaut_admission_menus.xml',
        'views/portal_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
