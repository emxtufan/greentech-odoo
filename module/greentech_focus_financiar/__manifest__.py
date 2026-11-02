{
    'name': 'GreenTech – Focus financiar',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'author': 'Greentech Professionals SRL',
    'depends': ['base', 'account'],
    'data': ['views/menu_visibility_views.xml'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
