"""ASCII-named entry point for the local browser reader."""

import importlib.util
from pathlib import Path
import sys


def load_reader_module():
    source = Path(__file__).with_name('作文朗读网页.py')
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location('voxcpm_reader', source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'无法加载朗读工具：{source}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    load_reader_module().main()
