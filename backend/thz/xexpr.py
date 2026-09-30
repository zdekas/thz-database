"""Safe evaluation of a user-typed numpy axis, e.g. `np.linspace(0.2, 3, 100)`."""
import ast
import operator
import re

import numpy as np

MAX_POINTS = 200_000

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow,
}
_KWARGS = {"num", "endpoint", "base", "start", "stop", "step"}


def _check(n):
    if not np.isfinite(n) or n > MAX_POINTS:
        raise ValueError(f"too many points (limit {MAX_POINTS})")
    return int(n)


def _spaced(func):
    def wrapper(start, stop, num=50, **kw):
        return func(start, stop, _check(num), **kw)
    return wrapper


def _arange(*args, **kw):
    start, stop, step = 0.0, None, 1.0
    if len(args) == 1:
        stop = args[0]
    elif len(args) == 2:
        start, stop = args
    elif len(args) == 3:
        start, stop, step = args
    start, stop, step = kw.get("start", start), kw.get("stop", stop), kw.get("step", step)
    if stop is None or step == 0:
        raise ValueError("bad arange arguments")
    _check(abs((stop - start) / step))
    return np.arange(start, stop, step)


_FUNCS = {
    "linspace": _spaced(np.linspace),
    "logspace": _spaced(np.logspace),
    "geomspace": _spaced(np.geomspace),
    "arange": _arange,
    "array": lambda x: np.asarray(x, dtype=float),
}


def _ev(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float, bool):
        return node.value if isinstance(node.value, bool) else float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _ev(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, (ast.List, ast.Tuple)):
        if len(node.elts) > MAX_POINTS:
            raise ValueError(f"too many points (limit {MAX_POINTS})")
        return [_ev(e) for e in node.elts]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("np", "numpy"):
        if node.attr == "pi":
            return float(np.pi)
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ("np", "numpy") \
            else f.id if isinstance(f, ast.Name) else None
        if name in _FUNCS and all(k.arg in _KWARGS for k in node.keywords):
            return _FUNCS[name](*[_ev(a) for a in node.args], **{k.arg: _ev(k.value) for k in node.keywords})
    raise ValueError("only numbers, lists, + - * / ** and np.linspace / np.arange / np.logspace / "
                     "np.geomspace / np.array are allowed")


def strip_assignment(text):
    """'x = np.linspace(...)' -> 'np.linspace(...)'"""
    return re.sub(r"^\s*[A-Za-z_]\w*\s*=\s*", "", text.strip())


def parse_x(text):
    text = strip_assignment(text)
    if len(text) > 2000:
        raise ValueError("expression too long")
    try:
        x = np.asarray(_ev(ast.parse(text, mode="eval").body), dtype=float).ravel()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"cannot evaluate expression ({exc})")
    if x.size == 0 or x.size > MAX_POINTS:
        raise ValueError(f"x must have between 1 and {MAX_POINTS} points")
    if not np.all(np.isfinite(x)):
        raise ValueError("x contains non-finite values")
    return x
