import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Any, Dict, List, Optional


def format_timestamp(ts: float) -> str:
    return f"{ts:.6f}"


def escape_xml_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def build_trace_element(events: List[Dict[str, Any]], metadata: Dict[str, Any],
                       schema_version: str = "2.1") -> ET.Element:
    root = ET.Element('trace')
    root.set('schema_version', schema_version)
    
    metadata_elem = ET.SubElement(root, 'metadata')
    for key, value in metadata.items():
        elem = ET.SubElement(metadata_elem, key)
        elem.text = str(value)
    
    ET.SubElement(metadata_elem, 'schema_version').text = schema_version
    
    events_elem = ET.SubElement(root, 'events')
    
    for event in events:
        event_elem = ET.SubElement(events_elem, 'event')
        event_elem.set('id', str(event.get('id', '')))
        event_elem.set('type', event.get('type', ''))
        event_elem.set('timestamp', format_timestamp(event.get('timestamp', 0)))
        
        if 'thread_id' in event:
            ET.SubElement(event_elem, 'thread_id').text = str(event['thread_id'])
        if 'file' in event:
            ET.SubElement(event_elem, 'file').text = event['file']
        if 'function' in event:
            ET.SubElement(event_elem, 'function').text = event['function']
        if 'line' in event:
            ET.SubElement(event_elem, 'line').text = str(event['line'])
        if 'source' in event:
            ET.SubElement(event_elem, 'source').text = event['source']
        if 'caller' in event:
            ET.SubElement(event_elem, 'caller').text = event['caller']
        
        if 'delta' in event and event['delta']:
            delta_elem = ET.SubElement(event_elem, 'delta')
            for var_name, change in event['delta'].items():
                change_elem = ET.SubElement(delta_elem, 'change')
                change_elem.set('name', var_name)
                change_elem.set('action', change.get('action', ''))
                change_elem.set('type', change.get('type', 'unknown'))
                if 'old' in change:
                    ET.SubElement(change_elem, 'old').text = change['old']
                if 'new' in change:
                    ET.SubElement(change_elem, 'new').text = change['new']
        
        if 'arguments' in event and event['arguments']:
            args_elem = ET.SubElement(event_elem, 'arguments')
            for arg_name, arg_val in event['arguments'].items():
                arg_elem = ET.SubElement(args_elem, 'arg')
                arg_elem.set('name', arg_name)
                if isinstance(arg_val, tuple):
                    arg_elem.set('type', arg_val[1])
                    arg_elem.text = arg_val[0]
        
        if 'locals' in event and event['locals']:
            locals_elem = ET.SubElement(event_elem, 'locals')
            for var_name, var_val in event['locals'].items():
                var_elem = ET.SubElement(locals_elem, 'var')
                var_elem.set('name', var_name)
                if isinstance(var_val, tuple):
                    var_elem.set('type', var_val[1])
                    var_elem.text = var_val[0]
        
        if 'return_value' in event:
            ret_val = event['return_value']
            ret_elem = ET.SubElement(event_elem, 'return_value')
            ret_elem.set('name', 'return')
            if isinstance(ret_val, tuple):
                ret_elem.set('type', ret_val[1])
                ret_elem.text = ret_val[0]
        
        if 'exception' in event:
            exc = event['exception']
            exc_elem = ET.SubElement(event_elem, 'exception')
            ET.SubElement(exc_elem, 'type').text = exc.get('type', '')
            ET.SubElement(exc_elem, 'value').text = exc.get('value', '')
    
    return root


def xml_to_string(root: ET.Element, pretty: bool = True) -> str:
    if pretty:
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="  ")
    else:
        return ET.tostring(root, encoding='unicode')
