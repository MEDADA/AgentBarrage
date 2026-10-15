"""Read visible Notification Center banners through macOS Accessibility."""

from .wechat import extract_notifications

NOTIFICATION_CENTER_IDS = {"com.apple.notificationcenterui", "com.apple.NotificationCenter"}
ATTRIBUTES = ("AXRole", "AXTitle", "AXValue", "AXDescription", "AXIdentifier")
MAX_NODES = 350


def accessibility_trusted(prompt=False):
    try:
        import ApplicationServices as AX
        if prompt:
            return bool(AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True}))
        return bool(AX.AXIsProcessTrusted())
    except (ImportError, AttributeError):
        return False


def _attribute(AX, element, name):
    try:
        error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
        return value if error == 0 else None
    except (TypeError, ValueError):
        return None


def _tree(AX, element, budget, depth=0):
    if depth > 9 or budget[0] <= 0:
        return {"children": []}
    budget[0] -= 1
    result = {"children": []}
    for attribute in ATTRIBUTES:
        value = _attribute(AX, element, attribute)
        if isinstance(value, str):
            result[attribute[2:].lower()] = value[:160]
    children = _attribute(AX, element, "AXChildren")
    if isinstance(children, (list, tuple)):
        result["children"] = [_tree(AX, child, budget, depth + 1) for child in children[:32]]
    return result


def visible_wechat_notifications():
    """Read only currently exposed Notification Center windows, if permitted."""
    import ApplicationServices as AX
    from AppKit import NSWorkspace

    if not AX.AXIsProcessTrusted():
        return []
    notifications = []
    budget = [MAX_NODES]
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.bundleIdentifier() or "") not in NOTIFICATION_CENTER_IDS:
            continue
        root = AX.AXUIElementCreateApplication(app.processIdentifier())
        AX.AXUIElementSetMessagingTimeout(root, 0.25)
        windows = _attribute(AX, root, "AXWindows")
        if not isinstance(windows, (list, tuple)):
            continue
        for window in windows[:12]:
            notifications.extend(extract_notifications(_tree(AX, window, budget)))
            if budget[0] <= 0:
                break
    return notifications
