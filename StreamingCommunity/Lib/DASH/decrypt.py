# 25.07.25

import os
import re
import time
import subprocess
import threading


# External libraries
from rich.console import Console
from tqdm import tqdm


# Internal utilities
from StreamingCommunity.Util.os import get_bento4_decrypt_path, get_bento4_dump_path
from StreamingCommunity.Util import config_manager, Colors


# Variable
console = Console()
extension_output = config_manager.config.get("M3U8_CONVERSION", "extension")
CLEANUP_TMP = config_manager.config.get_bool('M3U8_DOWNLOAD', 'cleanup_tmp_folder')


def detect_encryption_with_mp4dump(file_path: str):
    """
    Detect encryption method using mp4dump.
    
    Args:
        file_path: Path to encrypted MP4/M4S file
        
    Returns:
        Encryption method: 'ctr', 'cbc', or 'unknown'
    """
    mp4dump_path = get_bento4_dump_path()
    
    try:
        cmd = [mp4dump_path, file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            console.print(f"[red]mp4dump error: {result.stderr[:200]}")
            return 'unknown'
        
        output = result.stdout
        scheme_pattern = r'scheme_type\s*=\s*(\w+)'
        match = re.search(scheme_pattern, output, re.IGNORECASE)
        
        if match:
            scheme = match.group(1).lower()
            
            # cenc and cens use AES-CTR
            if scheme in ['cenc', 'cens']:
                return 'ctr'
            
            # cbcs and cbc1 use AES-CBC
            elif scheme in ['cbcs', 'cbc1']:
                return 'cbc'
        
        # Fallback: check default_per_sample_iv_size in tenc box
        # 8 bytes = CTR, 16 bytes = CBC
        iv_size_pattern = r'default_per_sample_iv_size\s*=\s*(\d+)'
        iv_match = re.search(iv_size_pattern, output, re.IGNORECASE)
        
        if iv_match:
            iv_size = int(iv_match.group(1))
            if iv_size == 8:
                return 'ctr'
            elif iv_size == 16:
                return 'cbc'
        
        return 'unknown'
        
    except Exception as e:
        console.print(f"[red]Error detecting encryption: {e}")
        return 'unknown'


def _create_progress_bar(file_type: str) -> tqdm:
    """Create a styled progress bar for decryption process."""
    bar_format = (
        f"{Colors.YELLOW}DECRYPT{Colors.CYAN} {file_type}{Colors.WHITE}: "
        f"{Colors.MAGENTA}{{bar:40}} "
        f"{Colors.LIGHT_GREEN}{{n_fmt}}{Colors.WHITE}/{Colors.CYAN}{{total_fmt}} "
        f"{Colors.DARK_GRAY}[{Colors.YELLOW}{{elapsed}}{Colors.WHITE} < {Colors.CYAN}{{remaining}}{Colors.DARK_GRAY}] "
        f"{Colors.WHITE}{{postfix}}"
    )
    return tqdm(total=100, bar_format=bar_format, unit="", ncols=150)


def _monitor_decryption_progress(output_path: str, file_size: int, progress_bar: tqdm) -> None:
    """
    Monitor output file growth and update progress bar.
    
    Args:
        output_path: Path to the output file being created
        file_size: Expected final file size
        progress_bar: Progress bar to update
    """
    last_size = 0
    max_attempts = 100
    
    for _ in range(max_attempts):
        if os.path.exists(output_path):
            current_size = os.path.getsize(output_path)
            if current_size > 0:
                progress_percent = min(int((current_size / file_size) * 100), 100)
                progress_bar.n = progress_percent
                progress_bar.refresh()
                
                # Stop if file size hasn't changed (decryption complete)
                if current_size == last_size and current_size > 0:
                    break
                
                last_size = current_size
        
        time.sleep(0.1)


def _try_decrypt(cmd: list, output_path: str, timeout: int = 60) -> bool:
    """
    Attempt decryption with given command.
    
    Args:
        cmd: Command to execute
        output_path: Path where decrypted file should be created
        timeout: Command timeout in seconds
        
    Returns:
        True if decryption succeeded, False otherwise
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (
            result.returncode == 0 and 
            os.path.exists(output_path) and 
            os.path.getsize(output_path) > 1000
        )
    
    except (subprocess.TimeoutExpired, Exception) as e:
        console.print(f"[red]Decryption attempt failed: {e}")
        return False


def decrypt_with_mp4decrypt(file_type: str, encrypted_path: str, kid: str, key: str, output_path: str = None) -> str:
    """
    Decrypt an MP4/M4S file using mp4decrypt with automatic encryption detection.

    Args:
        file_type: Type of file ('video' or 'audio')
        encrypted_path: Path to encrypted file
        kid: Hexadecimal KID (Key ID)
        key: Hexadecimal decryption key
        output_path: Output path for decrypted file (auto-generated if None)

    Returns:
        Path to decrypted file if successful, None otherwise
    """
    if not output_path:
        base_name = os.path.splitext(encrypted_path)[0]
        output_path = f"{base_name}_decrypted.{extension_output}"

    # Get file info
    file_size = os.path.getsize(encrypted_path)
    mp4decrypt_path = get_bento4_decrypt_path()
    
    # Auto-detect encryption method
    encryption_method = detect_encryption_with_mp4dump(encrypted_path)
    console.print(f"[cyan]Detected encryption: [yellow]{encryption_method.upper()}")
    kid_clean = str(kid).lower()
    key_lower = str(key).lower()

    # Create progress bar
    progress_bar = _create_progress_bar(file_type)
    
    # Start monitoring thread
    monitor_thread = threading.Thread(
        target=_monitor_decryption_progress,
        args=(output_path, file_size, progress_bar),
        daemon=True
    )
    monitor_thread.start()
    success = False
    
    # Try decryption based on detected method
    if encryption_method == 'ctr':
        cmd = [mp4decrypt_path, "--key", f"{kid_clean}:{key_lower}", encrypted_path, output_path]
        success = _try_decrypt(cmd, output_path, timeout=300)
        
        if not success:
            console.print("[yellow]Trying alternative CTR key format...")
            cmd = [mp4decrypt_path, "--key", f"1:{key_lower}", encrypted_path, output_path]
            success = _try_decrypt(cmd, output_path, timeout=300)
    
    elif encryption_method == 'cbc':
        cmd = [mp4decrypt_path, "--key", f"{kid_clean}:{key_lower}", encrypted_path, output_path]
        success = _try_decrypt(cmd, output_path, timeout=300)
    
    else:
        console.print("[yellow]Unknown encryption method, trying both CTR and CBC...")
        
        for method, key_format in [('CTR', f"{kid_clean}:{key_lower}"), ('CBC', f"{kid_clean}:{key_lower}")]:
            console.print(f"[cyan]Attempting {method} decryption...")
            temp_output = f"{output_path}.{method.lower()}"
            cmd = [mp4decrypt_path, "--key", key_format, encrypted_path, temp_output]
            
            if _try_decrypt(cmd, temp_output, timeout=300):
                os.rename(temp_output, output_path)
                console.print(f"[green]Success with {method}!")
                success = True
                break
            
            elif os.path.exists(temp_output):
                os.remove(temp_output)
    
    # Finalize progress bar
    progress_bar.n = 100
    progress_bar.refresh()
    progress_bar.close()
    
    # Verify success
    if success and os.path.exists(output_path):
        if CLEANUP_TMP and os.path.exists(encrypted_path):
            os.remove(encrypted_path)

        return output_path
    else:
        console.print(f"[bold red]✗ Decryption failed for {file_type}")
        return None