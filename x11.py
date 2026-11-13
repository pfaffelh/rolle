"""Kleine Xlib-Helfer (über ctypes) für Dinge, die Tk unter X11 nicht selbst kann:
Fenster auf allen Arbeitsflächen zeigen und Fenster aktivieren.
Unter GNOME/Wayland laufen Tk-Programme über XWayland, das funktioniert dort genauso.
Alle Funktionen schlagen still fehl, wenn X11 nicht verfügbar ist."""
import ctypes
import ctypes.util

_X = None
_DPY = None


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _XEvent(ctypes.Union):
    _fields_ = [("xclient", _XClientMessageEvent), ("pad", ctypes.c_long * 24)]


def _verbindung():
    global _X, _DPY
    if _DPY is None:
        _X = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
        _X.XOpenDisplay.restype = ctypes.c_void_p
        _X.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _X.XInternAtom.restype = ctypes.c_ulong
        _X.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        _X.XDefaultRootWindow.restype = ctypes.c_ulong
        _X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _X.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                  ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(ctypes.c_uint)]
        _X.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
                                  ctypes.POINTER(_XEvent)]
        _X.XFlush.argtypes = [ctypes.c_void_p]
        _X.XFree.argtypes = [ctypes.c_void_p]
        _DPY = _X.XOpenDisplay(None)
        if not _DPY:
            raise OSError("keine X11-Verbindung")
    return _X, _DPY


def _hauptfenster(widget):
    """X-ID des Tk-Wrapper-Fensters (Elternfenster von winfo_id) – das sieht der Fenstermanager."""
    x, dpy = _verbindung()
    root, eltern, kinder, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p(), ctypes.c_uint()
    x.XQueryTree(dpy, widget.winfo_id(), ctypes.byref(root), ctypes.byref(eltern),
                 ctypes.byref(kinder), ctypes.byref(n))
    if kinder.value:
        x.XFree(kinder)
    return eltern.value


def _nachricht(widget, typ, daten):
    x, dpy = _verbindung()
    ev = _XEvent()
    ev.xclient.type = 33  # ClientMessage
    ev.xclient.send_event = 1
    ev.xclient.window = _hauptfenster(widget)
    ev.xclient.message_type = x.XInternAtom(dpy, typ.encode(), 0)
    ev.xclient.format = 32
    for i, d in enumerate(daten):
        ev.xclient.data[i] = x.XInternAtom(dpy, d.encode(), 0) if isinstance(d, str) else d
    maske = (1 << 19) | (1 << 20)  # SubstructureNotify | SubstructureRedirect
    x.XSendEvent(dpy, x.XDefaultRootWindow(dpy), 0, maske, ctypes.byref(ev))
    x.XFlush(dpy)


def auf_allen_arbeitsflaechen(widget):
    """Fenster auf allen Arbeitsflächen zeigen (_NET_WM_STATE_STICKY). Erst nach dem Anzeigen aufrufen."""
    try:
        _nachricht(widget, "_NET_WM_STATE", [1, "_NET_WM_STATE_STICKY", 0, 1, 0])
    except Exception:
        pass


def aktivieren(widget):
    """Fenster nach vorne holen wie ein Fensterwechsler (Quelle 2 = Pager) –
    das lässt GNOME zu, auch wenn es sonst das 'Fokus-Stehlen' verhindert."""
    try:
        _nachricht(widget, "_NET_ACTIVE_WINDOW", [2, 0, 0, 0, 0])
    except Exception:
        pass
