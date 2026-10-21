"""Read visible Notification Center banners through macOS Accessibility."""

from .wechat import extract_notifications

NOTIFICATION_CENTER_IDS = {"com.apple.notificationcenterui", "com.apple.NotificationCenter"}
ATTRIBUTES = (
    "AXRole",
    "AXTitle",
    "AXValue",
    "AXDescription",
    "AXIdentifier",
    "AXSubrole",
    "AXStackingIdentifier",
    "AXAttributedDescription",
)
MAX_NODES = 350
BANNER_SUBROLES = ("banner", "alert")


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


def _coerce_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    string_fn = getattr(value, "string", None)
    if callable(string_fn):
        try:
            text = string_fn()
            return text if isinstance(text, str) else None
        except (TypeError, ValueError, AttributeError):
            return None
    return None


def _tree(AX, element, budget, depth=0):
    if depth > 9 or budget[0] <= 0:
        return {"children": []}
    budget[0] -= 1
    result = {"children": []}
    for attribute in ATTRIBUTES:
        value = _coerce_value(_attribute(AX, element, attribute))
        if not value:
            continue
        key = attribute[2:].lower()
        if key == "attributeddescription":
            if not result.get("description"):
                result["description"] = value[:160]
            continue
        result[key] = value[:160]
    children = _attribute(AX, element, "AXChildren")
    if isinstance(children, (list, tuple)):
        result["children"] = [_tree(AX, child, budget, depth + 1) for child in children[:32]]
    return result


def _looks_like_banner(node):
    role = (node.get("role") or "").lower()
    subrole = (node.get("subrole") or "").lower()
    if "systemdialog" in role.replace(" ", ""):
        return True
    return any(token in subrole for token in BANNER_SUBROLES)


def _collect_from_root(AX, root, budget):
    notifications = []
    seen = set()

    def take(element):
        if budget[0] <= 0:
            return
        node = _tree(AX, element, budget)
        marker = id(element)
        if marker in seen:
            return
        seen.add(marker)
        notifications.extend(extract_notifications(node))

    windows = _attribute(AX, root, "AXWindows")
    if isinstance(windows, (list, tuple)):
        for window in windows[:12]:
            take(window)
            if budget[0] <= 0:
                return notifications

    children = _attribute(AX, root, "AXChildren")
    if isinstance(children, (list, tuple)):
        for child in children[:32]:
            if budget[0] <= 0:
                break
            node = _tree(AX, child, budget)
            if _looks_like_banner(node) or node.get("children"):
                marker = id(child)
                if marker not in seen:
                    seen.add(marker)
                    notifications.extend(extract_notifications(node))
    return notifications


def visible_wechat_notifications():
    """Read currently exposed Notification Center banners, if permitted."""
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
        notifications.extend(_collect_from_root(AX, root, budget))
        if budget[0] <= 0:
            break
    return notifications
