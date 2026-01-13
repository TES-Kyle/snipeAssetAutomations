"""UI stub helpers for Tkinter-based unit tests."""


class DummyWidget:
    def __init__(self, *args, **kwargs):
        self._config = {}
        self._value = ""

    def pack(self, *args, **kwargs):
        return None

    def grid(self, *args, **kwargs):
        return None

    def bind(self, *args, **kwargs):
        return None

    def focus_set(self):
        return None

    def config(self, *args, **kwargs):
        self._config.update(kwargs)
        return None

    def configure(self, *args, **kwargs):
        self._config.update(kwargs)
        return None


class DummyWindow(DummyWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._width = 500
        self._height = 150

    def geometry(self, spec):
        if isinstance(spec, str) and "x" in spec:
            size_part = spec.split("+", 1)[0]
            if "x" in size_part:
                w, h = size_part.split("x", 1)
                if w.isdigit():
                    self._width = int(w)
                if h.isdigit():
                    self._height = int(h)
        return None

    def update_idletasks(self):
        return None

    def winfo_screenwidth(self):
        return 1200

    def winfo_screenheight(self):
        return 800

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height

    def after(self, *_args, **_kwargs):
        return None

    def destroy(self):
        return None


class DummyEntry(DummyWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = ""

    def delete(self, *_args, **_kwargs):
        self._value = ""

    def insert(self, *_args):
        if len(_args) >= 2:
            self._value = _args[1]

    def get(self):
        return self._value


class DummyText(DummyWidget):
    def delete(self, *_args, **_kwargs):
        self._value = ""

    def insert(self, *_args):
        if len(_args) >= 2:
            self._value += _args[1]

    def get(self, *_args):
        return self._value


class DummyStringVar:
    instances = []

    def __init__(self, value=None):
        self._value = "" if value is None else value
        DummyStringVar.instances.append(self)

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyIntVar(DummyStringVar):
    pass


class DummyBoolVar(DummyStringVar):
    pass


class DummyCombobox(DummyWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._values = []
        self._textvariable = kwargs.get("textvariable")

    def set(self, value):
        if self._textvariable is not None:
            self._textvariable.set(value)

    def __setitem__(self, key, value):
        if key == "values":
            self._values = value

    def __getitem__(self, key):
        if key == "values":
            return self._values
        raise KeyError(key)


class DummyButton(DummyWidget):
    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command = kwargs.get("command")
        DummyButton.instances.append(self)


class DummyDateEntry(DummyWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class DummyMessagebox:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message):
        self.calls.append(("error", title, message))
        return None

    def showwarning(self, title, message):
        self.calls.append(("warning", title, message))
        return None

    def askretrycancel(self, title, message):
        self.calls.append(("retrycancel", title, message))
        return False


def reset_ui_state():
    DummyButton.instances = []
    DummyStringVar.instances = []
