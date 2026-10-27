"""Give the dedicated browser desktop one workspace and maximized windows."""
import xml.etree.ElementTree as ET

path = '/etc/xdg/openbox/rc.xml'
namespace = 'http://openbox.org/3.4/rc'
ET.register_namespace('', namespace)
tag = lambda name: f'{{{namespace}}}{name}'
tree = ET.parse(path)
root = tree.getroot()
root.find(f'{tag("desktops")}/{tag("number")}').text = '1'
for browser_class in ('Google-chrome',):
    application = ET.SubElement(root.find(tag('applications')), tag('application'), {'class': browser_class})
    ET.SubElement(application, tag('maximized')).text = 'yes'

# There is no taskbar, so an iconified window can never be brought back.
root.find(f'{tag("theme")}/{tag("titleLayout")}').text = 'NLMC'
def hides_windows(binding):
    for action in binding.iter(tag('action')):
        if action.get('name') in ('Iconify', 'ToggleShowDesktop'):
            return True
        menu = action.find(tag('menu'))
        if action.get('name') == 'ShowMenu' and menu is not None and menu.text == 'client-menu':
            return True
    return False
for parent in list(root.iter()):
    for binding in [child for child in parent if child.tag in (tag('keybind'), tag('mousebind'))]:
        if hides_windows(binding):
            parent.remove(binding)
# A global binding remains reachable while Chrome covers the entire desktop.
binding = ET.SubElement(root.find(tag('keyboard')), tag('keybind'), {'key': 'C-A-s'})
action = ET.SubElement(binding, tag('action'), {'name': 'ShowMenu'})
ET.SubElement(action, tag('menu')).text = 'desktop-scale-menu'
tree.write(path, encoding='UTF-8', xml_declaration=True)

menu_namespace = 'http://openbox.org/3.4/menu'
ET.register_namespace('', menu_namespace)
mtag = lambda name: f'{{{menu_namespace}}}{name}'
menus = ET.Element(mtag('openbox_menu'))
scale_menu = ET.SubElement(menus, mtag('menu'), {'id': 'desktop-scale-menu', 'label': 'Display scale'})
for label, value in (
        ('Auto (client display)', 'auto'),
        ('100% - Phone compatibility', '100'),
        ('150% - Larger text', '150'),
        ('200% - Mac Retina / 2x phone', '200'),
        ('300% - Phone Retina', '300')):
    item = ET.SubElement(scale_menu, mtag('item'), {'label': label})
    action = ET.SubElement(item, mtag('action'), {'name': 'Execute'})
    ET.SubElement(action, mtag('command')).text = f'/usr/local/bin/display-scale.py set {value}'
root_menu = ET.SubElement(menus, mtag('menu'), {'id': 'root-menu', 'label': 'Browser desktop'})
ET.SubElement(root_menu, mtag('menu'), {'id': 'desktop-scale-menu'})
ET.ElementTree(menus).write('/etc/xdg/openbox/menu.xml', encoding='UTF-8', xml_declaration=True)
