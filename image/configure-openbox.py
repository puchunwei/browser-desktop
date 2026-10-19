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
tree.write(path, encoding='UTF-8', xml_declaration=True)
