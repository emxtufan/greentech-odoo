"""Ascunde meniurile din bara de aplicații, păstrând doar zona financiară."""

HIDDEN_MENUS = [
    'mail.menu_root_discuss',
    'calendar.mail_menu_calendar',
    'contacts.menu_contacts',
    'sale.sale_menu_root',
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',
    'purchase.menu_purchase_root',
    'stock.menu_stock_root',
    'hr.menu_hr_root',
    'hr_attendance.menu_hr_attendance_root',
    'hr_holidays.menu_hr_holidays_root',
    'hr_expense.menu_hr_expense_root',
    'utm.menu_link_tracker_root',
    'base.menu_tests',
]


def post_init_hook(env):
    for xmlid in HIDDEN_MENUS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.active = False


def uninstall_hook(env):
    Menu = env['ir.ui.menu'].with_context(active_test=False)
    for xmlid in HIDDEN_MENUS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            Menu.browse(menu.id).active = True
