import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "做装备" / "src"))

from xydp.runtime import platform_root
from xydp.storage_paths import configure_platform_temp

configure_platform_temp(platform_root())

from xydp.gui import main


if __name__ == "__main__":
    main()
