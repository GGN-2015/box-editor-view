import sys

from box_editor_view import platform_window


class FakeHandle:
    def __init__(self, value):
        self.value = value

    def getIntHandle(self):
        return self.value


class FakeWindow:
    def __init__(self, value):
        self.value = value
        self.requested_properties = []

    def getWindowHandle(self):
        return FakeHandle(self.value)

    def requestProperties(self, props):
        self.requested_properties.append(props)


def test_window_handle_as_int_uses_panda_window_handle():
    assert platform_window._window_handle_as_int(FakeWindow(12345)) == 12345


def test_window_handle_as_int_rejects_missing_or_zero_handles():
    assert platform_window._window_handle_as_int(None) is None
    assert platform_window._window_handle_as_int(FakeWindow(0)) is None
    assert platform_window._window_handle_as_int(FakeWindow("not-a-handle")) is None


def test_disable_ime_noops_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert platform_window.disable_ime_for_window(FakeWindow(12345)) is False


def test_disable_ime_calls_windows_imm32_when_layout_is_ime(monkeypatch):
    calls = []

    class FakeAssociateContext:
        argtypes = None
        restype = None

        def __call__(self, hwnd, context):
            calls.append((hwnd.value, context))
            return True

    class FakeImmIsIme:
        argtypes = None
        restype = None

        def __call__(self, keyboard_layout):
            calls.append(("is_ime", getattr(keyboard_layout, "value", keyboard_layout)))
            return True

    class FakeGetKeyboardLayout:
        argtypes = None
        restype = None

        def __call__(self, _thread_id):
            return 67890

    class FakeImm32:
        ImmIsIME = FakeImmIsIme()
        ImmAssociateContext = FakeAssociateContext()

    class FakeUser32:
        GetKeyboardLayout = FakeGetKeyboardLayout()

    monkeypatch.setattr(sys, "platform", "win32")

    def fake_windll(name, **_kwargs):
        return FakeImm32() if name == "imm32" else FakeUser32()

    monkeypatch.setattr(platform_window.ctypes, "WinDLL", fake_windll, raising=False)

    assert platform_window.disable_ime_for_window(FakeWindow(12345)) is True
    assert calls == [("is_ime", 67890), (12345, None)]


def test_disable_ime_skips_windows_call_when_layout_is_not_ime(monkeypatch):
    calls = []

    class FakeImmIsIme:
        argtypes = None
        restype = None

        def __call__(self, _keyboard_layout):
            return False

    class FakeAssociateContext:
        argtypes = None
        restype = None

        def __call__(self, hwnd, context):
            calls.append((hwnd.value, context))
            return True

    class FakeGetKeyboardLayout:
        argtypes = None
        restype = None

        def __call__(self, _thread_id):
            return 67890

    class FakeImm32:
        ImmIsIME = FakeImmIsIme()
        ImmAssociateContext = FakeAssociateContext()

    class FakeUser32:
        GetKeyboardLayout = FakeGetKeyboardLayout()

    monkeypatch.setattr(sys, "platform", "win32")

    def fake_windll(name, **_kwargs):
        return FakeImm32() if name == "imm32" else FakeUser32()

    monkeypatch.setattr(platform_window.ctypes, "WinDLL", fake_windll, raising=False)

    assert platform_window.disable_ime_for_window(FakeWindow(12345)) is False
    assert calls == []


def test_maximize_window_uses_show_window_on_windows(monkeypatch):
    calls = []

    class FakeShowWindow:
        argtypes = None
        restype = None

        def __call__(self, hwnd, command):
            calls.append((hwnd.value, command))
            return True

    class FakeUser32:
        ShowWindow = FakeShowWindow()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform_window.ctypes, "WinDLL", lambda *_args, **_kwargs: FakeUser32(), raising=False)

    assert platform_window.maximize_window(FakeWindow(12345)) is True
    assert calls == [(12345, platform_window.SW_MAXIMIZE)]


def test_maximize_window_falls_back_to_fullscreen_request(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    window = FakeWindow(12345)

    assert platform_window.maximize_window(window) is True
    assert len(window.requested_properties) == 1
    assert window.requested_properties[0].getFullscreen() is True
