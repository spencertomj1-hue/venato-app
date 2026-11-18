"""
Lets a package that was split out of one big module keep behaving like that one module.

Callers (and tests) use `store.x` as if store were still a single file. A plain re-export in the
package's __init__ copies each value once, which breaks two things:

- assignment: `store.local_now = fake` (what monkeypatch does) would change only the package's
  copy, not the submodules that call local_now. Here it rebinds the name everywhere it points
  at the same object, as if there were still one namespace. Reloading the package
  (importlib.reload, as the tests do) puts back what was replaced, as reloading one file did.
- values that follow the settings or the environment (store.SLOTS, store.DB_PATH): these are
  "live" names, read through a function on every access, so they can't go stale. A live name
  with a setter can be pointed elsewhere (store.DB_PATH = path); deleting it undoes that.
"""

import sys
import types

_MISSING = object()


class Facade(types.ModuleType):
    def __getattr__(self, name):                       # only called for names not set on the package
        live = self.__dict__.get("_live", {})
        if name in live:
            return live[name][0]()
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        live = self.__dict__.get("_live", {})
        if name in live:
            setter = live[name][1]
            if setter is None:
                raise AttributeError(f"{self.__name__}.{name} is worked out from the settings; it can't be set")
            setter(value)
            return
        old = self.__dict__.get(name, _MISSING)
        if old is not _MISSING:
            replaced = self.__dict__.setdefault("_replaced", {})
            prefix = self.__name__ + "."
            for key, module in list(sys.modules.items()):
                if key.startswith(prefix) and module is not None and module.__dict__.get(name, _MISSING) is old:
                    original = replaced.setdefault((key, name), old)
                    if value is original:
                        del replaced[(key, name)]
                    module.__dict__[name] = value
        super().__setattr__(name, value)

    def __delattr__(self, name):                       # a live name: back to its usual value
        live = self.__dict__.get("_live", {})
        if name in live and live[name][1] is not None:
            live[name][1](None)
        else:
            super().__delattr__(name)


def install(name, live=None):
    """Make the package `name` a Facade. live: {attribute: (getter, setter or None)};
    the setter gets None when the attribute is deleted."""
    module = sys.modules[name]
    for (key, attr), original in module.__dict__.pop("_replaced", {}).items():   # a reload: as it was
        sys.modules[key].__dict__[attr] = original
        module.__dict__[attr] = original
    for _, setter in module.__dict__.get("_live", {}).values():
        if setter is not None:
            setter(None)
    module.__class__ = Facade
    module.__dict__["_live"] = dict(live or {})
