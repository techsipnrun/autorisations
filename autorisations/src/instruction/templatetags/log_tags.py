from django import template

register = template.Library()

@register.filter
def log_level(line):
    if "ERROR" in line:
        return "ERROR"
    if "WARNING" in line:
        return "WARNING"
    if "INFO" in line:
        return "INFO"
    if "Exception" in line or "Traceback" in line:
        return "EXCEPTION"
    return "OTHER"


@register.filter
def get_item(dictionary, key):
    try:
        return dictionary.get(key)
    except:
        return None

