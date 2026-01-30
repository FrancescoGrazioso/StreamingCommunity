# 29.01.26

import os


# External libraries
from rich.console import Console


# Internal utilities
from StreamingCommunity.utils.db_vault import DBVault
from StreamingCommunity.setup.binary_paths import binary_paths


# Logic
from .playready import get_playready_keys
from .widevine import get_widevine_keys


# Variable
console = Console()


class DRMManager:
    def __init__(self, widevine_device_path: str = None, playready_device_path: str = None, widevine_remote_cdm_api: list[str] = None, playready_remote_cdm_api: list[str] = None):
        """
        Initialize DRM Manager with configuration file paths and database.
        """
        self.db = DBVault(os.path.join(binary_paths.get_binary_directory(), 'drm_keys.db'))
        self.widevine_device_path = widevine_device_path
        self.playready_device_path = playready_device_path
        self.widevine_remote_cdm_api = widevine_remote_cdm_api
        self.playready_remote_cdm_api = playready_remote_cdm_api
    
    def get_wv_keys(self, pssh_list: list[dict], license_url: str, headers: dict = None, key: str = None, kid_to_label: dict = None) -> list[str]:
        """
        Get Widevine keys with step: 
            1) Database lookup by license URL and PSSH
            2) Fallback search by KIDs only
            3) CDM extraction
                1) If .wvd file provided, use it
                2) Else, use remote CDM API if provided
        """
        # Handle pre-existing key
        if key:
            k_split = key.split(':')
            if len(k_split) == 2:
                result = [f"{k_split[0].replace('-', '').strip()}:{k_split[1].replace('-', '').strip()}"]
                console.print("[green] Using provided key")
                return result
        
        # Extract PSSH from first entry for database lookup
        pssh_val = pssh_list[0].get('pssh') if pssh_list else None
        
        if not pssh_val:
            console.print("[yellow]Warning: No PSSH provided for database lookup")
        
        # Step 1: Check database by license URL and PSSH
        if license_url and pssh_val:
            found_keys = self.db.get_keys_by_license_and_pssh(license_url, pssh_val, 'widevine')
            
            if found_keys:
                return found_keys
        
        # Step 2: Try fallback search by KIDs only
        kids = [item.get('kid', '').replace('-', '').strip().lower() for item in pssh_list if item.get('kid')]
        valid_kids = [k for k in kids if k and k != 'n/a']
        
        if valid_kids:
            found_keys = self.db.get_keys_for_kids(valid_kids, 'widevine')
            
            if found_keys:
                return found_keys
        
        # Step 3: Try CDM extraction
        try:
            keys = get_widevine_keys(pssh_list, license_url, self.widevine_device_path, self.widevine_remote_cdm_api, headers, key, kid_to_label)
                
            if keys:
                if license_url and pssh_val:
                    self.db.add_keys(keys, 'widevine', license_url, pssh_val, kid_to_label)
                return keys
            
            else:
                console.print("[yellow]CDM extraction returned no keys")
        
        except Exception as e:
            console.print(f"[red]CDM error: {e}")

        console.print("\n[red]All extraction methods failed for Widevine")
        return None
    
    def get_pr_keys(self, pssh_list: list[dict], license_url: str, headers: dict = None, key: str = None, kid_to_label: dict = None) -> list[str]:
        """
        Get PlayReady keys with step: 
            1) Database lookup by license URL and PSSH
            2) Fallback search by KIDs only
            3) CDM extraction
                1) If .prd file provided, use it
                2) Else, use remote CDM API if provided
        """
        # Handle pre-existing key
        if key:
            k_split = key.split(':')
            if len(k_split) == 2:
                result = [f"{k_split[0].replace('-', '').strip()}:{k_split[1].replace('-', '').strip()}"]
                console.print("[green] Using provided key")
                return result
        
        # Extract PSSH from first entry for database lookup
        pssh_val = pssh_list[0].get('pssh') if pssh_list else None
        
        if not pssh_val:
            console.print("[yellow]Warning: No PSSH provided for database lookup")
        
        # Step 1: Check database by license URL and PSSH
        if license_url and pssh_val:
            found_keys = self.db.get_keys_by_license_and_pssh(license_url, pssh_val, 'playready')
            
            if found_keys:
                return found_keys
        
        # Step 2: Try fallback search by KIDs only
        kids = [item.get('kid', '').replace('-', '').strip().lower() for item in pssh_list if item.get('kid')]
        valid_kids = [k for k in kids if k and k != 'n/a']
        
        if valid_kids:
            found_keys = self.db.get_keys_for_kids(valid_kids, 'playready')
            
            if found_keys:
                return found_keys
        
        # Step 3: Try CDM extraction
        try:
            keys = get_playready_keys(pssh_list, license_url, self.playready_device_path, self.playready_remote_cdm_api, headers, key, kid_to_label)
            
            if keys:
                if license_url and pssh_val:
                    self.db.add_keys(keys, 'playready', license_url, pssh_val, kid_to_label)
                return keys
            else:
                console.print("[yellow]CDM extraction returned no keys")
        
        except Exception as e:
            console.print(f"[red]CDM error: {e}")
        
        console.print("\n[red]All extraction methods failed for PlayReady")
        return None