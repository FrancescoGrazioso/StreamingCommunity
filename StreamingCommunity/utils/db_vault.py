# 29.01.26

import os
import sqlite3
from typing import List, Dict
from urllib.parse import urlparse


# External import
from rich.console import Console


# Variable
console = Console()


class DBVault:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database with schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Main table for storing DRM cache entries
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drm_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_url_license TEXT NOT NULL,
                    pssh TEXT NOT NULL,
                    drm_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 1,
                    UNIQUE(base_url_license, pssh, drm_type)
                )
            """)
            
            # Separate table for keys (one-to-many relationship)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drm_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_id INTEGER NOT NULL,
                    kid TEXT NOT NULL,
                    key TEXT NOT NULL,
                    label TEXT,
                    is_valid BOOLEAN DEFAULT 1,
                    FOREIGN KEY (cache_id) REFERENCES drm_cache(id) ON DELETE CASCADE,
                    UNIQUE(cache_id, kid)
                )
            """)
            
            # Indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_lookup 
                ON drm_cache(base_url_license, pssh, drm_type)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_keys_cache 
                ON drm_keys(cache_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_keys_kid 
                ON drm_keys(kid)
            """)
            
            conn.commit()

    def get_db_stats(self) -> Dict[str, object]:
        """Return statistics about the database."""
        stats = {'total_caches': 0, 'total_keys': 0, 'db_file_size': 0, 'top_caches_by_keys': [], 'top_accessed_caches': []}

        # File size
        try:
            if os.path.exists(self.db_path):
                stats['db_file_size'] = os.path.getsize(self.db_path)
        except Exception:
            stats['db_file_size'] = 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT COUNT(*) FROM drm_cache")
                stats['total_caches'] = cursor.fetchone()[0] or 0

                cursor.execute("SELECT COUNT(*) FROM drm_keys")
                stats['total_keys'] = cursor.fetchone()[0] or 0

                # Top caches by number of keys
                cursor.execute(
                    "SELECT cache_id, COUNT(*) as cnt FROM drm_keys GROUP BY cache_id ORDER BY cnt DESC LIMIT 5"
                )
                stats['top_caches_by_keys'] = [(row[0], row[1]) for row in cursor.fetchall()]

                # Top accessed caches
                cursor.execute(
                    "SELECT id, base_url_license, drm_type, access_count, last_accessed FROM drm_cache ORDER BY access_count DESC LIMIT 5"
                )
                top = []
                for row in cursor.fetchall():
                    top.append({
                        'id': row[0],
                        'base_url_license': row[1],
                        'drm_type': row[2],
                        'access_count': row[3],
                        'last_accessed': row[4]
                    })
                stats['top_accessed_caches'] = top

            except Exception as e:
                console.print(f"[red]Error collecting DB stats: {e}")

        return stats
    
    def _clean_license_url(self, license_url: str) -> str:
        """Extract base URL from license URL (remove query parameters and fragments)"""
        parsed = urlparse(license_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return base_url.rstrip('/')
    
    def add_key(self, kid: str, key: str, drm_type: str, license_url: str, pssh: str = None, label: str = None) -> bool:
        """Add a single DRM key to the database"""
        # Normalize inputs
        kid = kid.replace('-', '').strip().lower()
        key = key.replace('-', '').strip().lower()
        drm_type = drm_type.lower()
        base_url = self._clean_license_url(license_url)
        
        if drm_type not in ['widevine', 'playready']:
            console.print(f"[red]Invalid DRM type: {drm_type}. Must be 'widevine' or 'playready'.")
            return False
        
        if not pssh:
            console.print(f"[yellow]Warning: No PSSH provided for KID: {kid}")
            return False
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                # Check if cache entry exists
                cursor.execute("""
                    SELECT id FROM drm_cache 
                    WHERE base_url_license = ? AND pssh = ? AND drm_type = ?
                """, (base_url, pssh, drm_type))
                
                result = cursor.fetchone()
                
                if result:
                    cache_id = result[0]
                    
                    # Update access statistics
                    cursor.execute("""
                        UPDATE drm_cache 
                        SET last_accessed = CURRENT_TIMESTAMP, 
                            access_count = access_count + 1
                        WHERE id = ?
                    """, (cache_id,))
                    
                    # Check if key already exists
                    cursor.execute("""
                        SELECT id FROM drm_keys 
                        WHERE cache_id = ? AND kid = ?
                    """, (cache_id, kid))
                    
                    if cursor.fetchone():
                        console.print(f"\n[yellow]Key already exists for KID: {kid}")
                        conn.commit()
                        return False
                else:
                    # Create new cache entry
                    cursor.execute("""
                        INSERT INTO drm_cache (base_url_license, pssh, drm_type)
                        VALUES (?, ?, ?)
                    """, (base_url, pssh, drm_type))
                    cache_id = cursor.lastrowid
                
                # Insert key
                cursor.execute("""
                    INSERT INTO drm_keys (cache_id, kid, key, label)
                    VALUES (?, ?, ?, ?)
                """, (cache_id, kid, key, label))
                
                conn.commit()
                return True
                
            except sqlite3.IntegrityError as e:
                console.print(f"[yellow]Key already exists: {e}")
                return False
            except Exception as e:
                console.print(f"[red]Error adding key: {e}")
                conn.rollback()
                return False
    
    def add_keys(self, keys_list: List[str], drm_type: str, license_url: str, pssh: str = None, kid_to_label: Dict[str, str] = None) -> int:
        """Add multiple keys to the database at once."""
        if not keys_list:
            console.print("[yellow]No keys provided to add.")
            return 0
        
        added_count = 0
        for key_str in keys_list:
            if ':' in key_str:
                kid, key = key_str.split(':', 1)
                label = kid_to_label.get(kid.lower()) if kid_to_label else None
                
                if self.add_key(kid, key, drm_type, license_url, pssh, label):
                    added_count += 1
        
        return added_count
    
    def get_keys_by_license_and_pssh(self, license_url: str, pssh: str, drm_type: str) -> List[str]:
        """
        Retrieve all keys for a given license URL, PSSH, and DRM type.
        
        Args:
            license_url (str): License URL.
            pssh (str): PSSH value.
            drm_type (str): Either 'widevine' or 'playready'.
        
        Returns:
            list: List of "KID:KEY" strings found in database.
        """
        base_url = self._clean_license_url(license_url)
        drm_type = drm_type.lower()
        
        if drm_type not in ['widevine', 'playready']:
            console.print(f"[red]Invalid DRM type: {drm_type}")
            return []
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Find cache entry
            cursor.execute("""
                SELECT id FROM drm_cache 
                WHERE base_url_license = ? AND pssh = ? AND drm_type = ?
            """, (base_url, pssh, drm_type))
            
            result = cursor.fetchone()
            
            if not result:
                return []
            
            cache_id = result[0]
            
            # Update access statistics
            cursor.execute("""
                UPDATE drm_cache 
                SET last_accessed = CURRENT_TIMESTAMP, 
                    access_count = access_count + 1
                WHERE id = ?
            """, (cache_id,))
            
            # Retrieve all keys
            cursor.execute("""
                SELECT kid, key, label 
                FROM drm_keys 
                WHERE cache_id = ? AND is_valid = 1
            """, (cache_id,))
            
            keys = []
            for row in cursor.fetchall():
                kid, key, label = row
                keys.append(f"{kid}:{key}")
                
                # Display label if available
                info = []
                if label:
                    info.append(f"[red]{label}")
                info_str = f" [cyan]| {' | '.join(info)}" if info else ""
                
                console.print(f"[green] [LOCAL_DB] {drm_type.upper()}: [red]{kid}[cyan]:[green]{key}{info_str}")
            
            conn.commit()
            return keys
    
    def get_keys_for_kids(self, kid_list: List[str], drm_type: str, license_url: str = None, pssh: str = None) -> List[str]:
        """
        Retrieve multiple keys from the database by KID list.
        Can optionally filter by license URL and PSSH.
        
        Args:
            kid_list (list[str]): List of KIDs in hex format.
            drm_type (str): Either 'widevine' or 'playready'.
            license_url (str): Optional license URL filter.
            pssh (str): Optional PSSH filter.
        
        Returns:
            list: List of "KID:KEY" strings found in database.
        """
        if not kid_list:
            return []
        
        drm_type = drm_type.lower()
        
        if drm_type not in ['widevine', 'playready']:
            console.print(f"[red]Invalid DRM type: {drm_type}")
            return []
        
        # Normalize KIDs
        normalized_kids = [k.replace('-', '').strip().lower() for k in kid_list]
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if license_url and pssh:
                # Specific lookup
                base_url = self._clean_license_url(license_url)
                
                cursor.execute("""
                    SELECT id FROM drm_cache 
                    WHERE base_url_license = ? AND pssh = ? AND drm_type = ?
                """, (base_url, pssh, drm_type))
                
                result = cursor.fetchone()
                
                if not result:
                    return []
                
                cache_id = result[0]
                
                # Update access statistics
                cursor.execute("""
                    UPDATE drm_cache 
                    SET last_accessed = CURRENT_TIMESTAMP, 
                        access_count = access_count + 1
                    WHERE id = ?
                """, (cache_id,))
                
                # Get keys for specific cache entry
                placeholders = ','.join('?' * len(normalized_kids))
                cursor.execute(f"""
                    SELECT kid, key, label
                    FROM drm_keys 
                    WHERE cache_id = ? AND kid IN ({placeholders}) AND is_valid = 1
                """, [cache_id] + normalized_kids)
                
            else:
                # Search across all cache entries for this DRM type
                cursor.execute("""
                    SELECT c.id FROM drm_cache c
                    WHERE c.drm_type = ?
                """, (drm_type,))
                
                cache_ids = [row[0] for row in cursor.fetchall()]
                
                if not cache_ids:
                    return []
                
                # Get keys from any cache entry
                placeholders = ','.join('?' * len(normalized_kids))
                cache_placeholders = ','.join('?' * len(cache_ids))
                
                cursor.execute(f"""
                    SELECT kid, key, label 
                    FROM drm_keys 
                    WHERE cache_id IN ({cache_placeholders}) 
                        AND kid IN ({placeholders}) 
                        AND is_valid = 1
                """, cache_ids + normalized_kids)
            
            keys = []
            for row in cursor.fetchall():
                kid, key, label = row
                keys.append(f"{kid}:{key}")
                
                # Display label if available
                info = []
                if label:
                    info.append(f"[red]{label}")
                info_str = f" [cyan]| {' | '.join(info)}" if info else ""
                console.print(f"[green] [LOCAL_DB] Found {drm_type.upper()} key: [red]{kid}{info_str}")
            
            conn.commit()
            return keys