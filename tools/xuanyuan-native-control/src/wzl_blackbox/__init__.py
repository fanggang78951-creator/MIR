"""Wzl 编辑器黑盒差分实验工具。"""

from .diff import BinaryDiffReport, ChangeRange, compare_files

__all__ = ["BinaryDiffReport", "ChangeRange", "compare_files"]
