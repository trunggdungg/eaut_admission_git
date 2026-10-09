# -*- coding: utf-8 -*-
{
    'name': 'Eaut Admission',
    'version': '1.0',
    'summary': 'Cổng tuyển sinh: thí sinh nộp hồ sơ xét tuyển trên portal, phòng đào tạo kiểm tra và duyệt',
    'description': '''
        Mở rộng eaut_crm cho cổng portal tuyển sinh:
        - Thí sinh đăng ký tài khoản, nhập thông tin cá nhân, upload học bạ / căn cước / VNeID, chọn nguyện vọng.
        - Trạng thái hồ sơ: Cập nhật thông tin -> Hoàn thành hồ sơ -> Đang kiểm tra -> Đã hoàn thành.
        - Phòng đào tạo kiểm tra, yêu cầu bổ sung, chấp nhận / từ chối hồ sơ.
        - Hồ sơ được chấp nhận: đóng học phí để nhận giấy xác nhận nhập học (điều kiện đỗ tốt nghiệp).
    ''',
    'category': 'Services',
    'author': 'EAUT',
    'company': 'EAUT',
    'maintainer': 'EAUT',
    'website': '',
    'depends': ['base', 'mail', 'portal', 'eaut_crm'],
    'data': [
        'security/eaut_admission_groups.xml',
        'security/ir.model.access.csv',
        'security/eaut_admission_rules.xml',
        'data/eaut_admission_data.xml',
        'views/eaut_admission_application_views.xml',
        'views/eaut_admission_submission_views.xml',
        'views/eaut_admission_menus.xml',
        'views/portal_templates.xml',
        'report/eaut_admission_report.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
