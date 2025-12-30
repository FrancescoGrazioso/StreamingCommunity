# 18.07.25

import os
import shutil
from typing import Optional, Tuple


# External library
from rich.console import Console


# Logic
from .binary_paths import binary_paths


# Variable
console = Console()


def check_bento4_binary(binary_name: str) -> Optional[str]:
    """
    Check for a Bento4 binary and download if not found.
    Order: system PATH -> binary directory -> download from GitHub
    """
    system_platform = binary_paths.system
    binary_exec = f"{binary_name}.exe" if system_platform == "windows" else binary_name

    # STEP 1: Check system PATH
    binary_path = shutil.which(binary_exec)
    
    if binary_path:
        return binary_path

    # STEP 2: Check local binary directory
    binary_local = binary_paths.get_binary_path("bento4", binary_exec)
    if binary_local and os.path.isfile(binary_local):
        return binary_local

    # STEP 3: Download
    console.print(f"[red]{binary_exec} not found. Downloading ...")
    binary_downloaded = binary_paths.download_binary("bento4", binary_exec)

    if binary_downloaded:
        return binary_downloaded

    console.print(f"Failed to download {binary_exec}", style="red")
    return None


def check_bento4_tools() -> Optional[Tuple[str, str]]:
    """
    Ensure mp4decrypt and mp4dump are available.

    Returns:
        Tuple[str, str]: (mp4decrypt_path, mp4dump_path)
        None if one of them is missing
    """
    mp4decrypt_path = check_bento4_binary("mp4decrypt")
    mp4dump_path = check_bento4_binary("mp4dump")

    if not mp4decrypt_path or not mp4dump_path:
        return None

    return mp4decrypt_path, mp4dump_path