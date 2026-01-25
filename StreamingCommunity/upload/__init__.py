# 01.03.23

from .update import update as git_update
from .update import auto_update as binary_update


__all__ = [
    "git_update",
    "binary_update",
]