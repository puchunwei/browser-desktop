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
tree.write(path, encoding='UTF-8', xml_declaration=True)
