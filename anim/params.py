"""Generic nested-dataclass serialization helpers."""

from __future__ import annotations

import dataclasses
import types
from typing import Type, TypeVar, get_args, get_origin, get_type_hints

T = TypeVar("T")


def params_from_dict(cls: Type[T], d: dict) -> T:
    """Reconstruct a dataclass instance from a nested dict.

    Handles ``Optional[SomeDataclass]`` fields and plain dataclass fields
    by recursing into sub-dicts automatically.  Primitive fields, lists,
    and other types are passed through unchanged.

    Example::

        p = params_from_dict(AnimParams, json.loads(path.read_text()))
    """
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls} is not a dataclass")

    hints = get_type_hints(cls)
    kwargs: dict = {}

    for f in dataclasses.fields(cls):
        if f.name not in d:
            continue
        val = d[f.name]
        hint = hints[f.name]
        kwargs[f.name] = _coerce(hint, val)

    return cls(**kwargs)


def _coerce(hint: type, val: object) -> object:
    """Coerce *val* to match *hint*, recursing into dataclasses."""
    if val is None:
        return None

    # Plain dataclass field
    if dataclasses.is_dataclass(hint) and isinstance(val, dict):
        return params_from_dict(hint, val)

    # Union types (e.g. RotationConfig | None)
    if isinstance(hint, types.UnionType):
        union_args = hint.__args__
        for arg in union_args:
            if arg is type(None):
                continue
            if dataclasses.is_dataclass(arg) and isinstance(val, dict):
                return params_from_dict(arg, val)
        return val

    # list[Dataclass] fields (e.g. list[PrismDef])
    origin = get_origin(hint)
    if origin is list and isinstance(val, list):
        list_args = get_args(hint)
        if list_args and dataclasses.is_dataclass(list_args[0]):
            elem_cls = list_args[0]
            return [
                params_from_dict(elem_cls, item) if isinstance(item, dict) else item for item in val
            ]

    return val
