# 25.07.25

import os
import time
import struct
import asyncio
from typing import Dict, Optional
from urllib.parse import urlparse
from pathlib import Path


# External libraries
import httpx
from tqdm import tqdm
from rich.console import Console


# Internal utilities
from StreamingCommunity.Util.http_client import get_userAgent
from StreamingCommunity.Lib.HLS.estimator import M3U8_Ts_Estimator
from StreamingCommunity.Util import config_manager, Colors


# DASH single-file MP4 support
from ..MP4 import MP4_Downloader


# Config
console = Console()
REQUEST_MAX_RETRY = config_manager.config.get_int('REQUESTS', 'max_retry')
DEFAULT_VIDEO_WORKERS = config_manager.config.get_int('M3U8_DOWNLOAD', 'default_video_workers')
DEFAULT_AUDIO_WORKERS = config_manager.config.get_int('M3U8_DOWNLOAD', 'default_audio_workers')
SEGMENT_MAX_TIMEOUT = config_manager.config.get_int("M3U8_DOWNLOAD", "segment_timeout")
ENABLE_RETRY = config_manager.config.get_bool('M3U8_DOWNLOAD', 'enable_retry')
CLEANUP_TMP = config_manager.config.get_bool('M3U8_DOWNLOAD', 'cleanup_tmp_folder')


class MPD_Segments:
    def __init__(self, tmp_folder: str, representation: dict, pssh: str = None, custom_headers: Optional[Dict[str, str]] = None):
        """
        Initialize MPD_Segments with temp folder, representation, optional pssh.
        
        Parameters:
            - tmp_folder (str): Temporary folder to store downloaded segments
            - representation (dict): Selected representation with segment URLs
            - pssh (str, optional): PSSH string for decryption
        """
        self.tmp_folder = tmp_folder
        self.selected_representation = representation
        self.pssh = pssh
        self.custom_headers = custom_headers or {}

        self.enable_retry = ENABLE_RETRY
        self.download_interrupted = False
        self.info_nFailed = 0
        
        # OTHER INFO
        self.downloaded_segments = {}  # {idx: content_bytes}
        self.failed_segments = set()
        self.info_maxRetry = 0
        self.info_nRetry = 0
        
        # Progress
        self._last_progress_update = 0
        self._progress_update_interval = 0.1
        
        # Estimator for progress tracking
        self.estimator: Optional[M3U8_Ts_Estimator] = None
        
        # Synchronization
        self.segments_lock = asyncio.Lock()

    @staticmethod
    def _infer_url_ext(url: Optional[str]) -> Optional[str]:
        """Return lowercased extension without dot from URL path (ignores query/fragment)."""
        path = urlparse(url).path or ""
        ext = Path(path).suffix
        return ext.lstrip(".").lower() if ext else None

    def _get_segment_url_type(self) -> Optional[str]:
        """Determine segment URL type based on representation data"""
        rep = self.selected_representation or {}
        
        # Check explicit type first
        explicit_type = (rep.get("segment_url_type") or "").strip().lower()
        if explicit_type:
            return explicit_type

        segment_urls = rep.get("segment_urls") or []
        init_url = rep.get("init_url")
        
        # Single URL matching init_url indicates single-file MP4
        if len(segment_urls) == 1 and init_url and segment_urls[0] == init_url:
            return "mp4"

        # Multiple varying URLs indicate segmented content
        if self._has_varying_segment_urls(segment_urls):
            return "m4s"

        # Infer from first URL extension
        return self._infer_url_ext(segment_urls[0]) if segment_urls else None

    @staticmethod
    def _has_varying_segment_urls(segment_urls: list) -> bool:
        """Check if segment URLs represent different files"""
        if not segment_urls or len(segment_urls) <= 1:
            return False
        
        # Extract base paths (without query/fragment)
        base_paths = [urlparse(url).path for url in segment_urls]
        
        # URLs vary if paths are different
        return len(set(base_paths)) > 1

    def _merged_headers(self) -> Dict[str, str]:
        """Ensure UA exists while keeping caller-provided headers."""
        h = dict(self.custom_headers or {})
        h.setdefault("User-Agent", get_userAgent())
        return h

    def get_concat_path(self, output_dir: str = None):
        """
        Get the path for the concatenated output file.
        """
        rep_id = self.selected_representation['id']
        seg_type = self._get_segment_url_type()
        
        if seg_type in ("mp4", "m4s"):
            ext = "mp4"
        else:
            ext = "m4s"
            
        return os.path.join(output_dir or self.tmp_folder, f"{rep_id}_encrypted.{ext}")
        
    def get_segments_count(self) -> int:
        """
        Returns the total number of segments available in the representation.
        """
        if self._get_segment_url_type() == "mp4":
            return 1
        return len(self.selected_representation.get('segment_urls', []))

    def download_streams(self, output_dir: str = None, description: str = "DASH"):
        """
        Synchronous wrapper for download_segments, compatible with legacy calls.
        
        Parameters:
            - output_dir (str): Output directory for segments
            - description (str): Description for progress bar (e.g., "Video", "Audio Italian")
        """
        concat_path = self.get_concat_path(output_dir)
        seg_type = (self._get_segment_url_type() or "").lower()

        # Single-file MP4: download directly
        if seg_type == "mp4":
            rep = self.selected_representation
            url = (rep.get("segment_urls") or [None])[0] or rep.get("init_url")
            if not url:
                return {
                    "type": description,
                    "nFailed": 1,
                    "stopped": False,
                    "concat_path": concat_path,
                    "representation_id": rep.get("id"),
                    "pssh": self.pssh,
                }

            os.makedirs(output_dir or self.tmp_folder, exist_ok=True)
            try:
                downloaded_file, kill = MP4_Downloader(
                    url=url,
                    path=concat_path,
                    headers_=self._merged_headers(),
                    show_final_info=False
                )
                self.download_interrupted = bool(kill)
                return {
                    "type": description,
                    "nFailed": 0,
                    "stopped": bool(kill),
                    "concat_path": downloaded_file or concat_path,
                    "representation_id": rep.get("id"),
                    "pssh": self.pssh,
                }
            
            except KeyboardInterrupt:
                self.download_interrupted = True
                console.print("\n[red]Download interrupted by user (Ctrl+C).")
                return {
                    "type": description,
                    "nFailed": 1,
                    "stopped": True,
                    "concat_path": concat_path,
                    "representation_id": rep.get("id"),
                    "pssh": self.pssh,
                }

        # Run async download for segmented content
        try:
            res = asyncio.run(self.download_segments(output_dir=output_dir, description=description))
        except KeyboardInterrupt:
            self.download_interrupted = True
            console.print("\n[red]Download interrupted by user (Ctrl+C).")
            res = {"type": description, "nFailed": 0, "stopped": True}

        return {
            **(res or {}),
            "concat_path": concat_path,
            "representation_id": self.selected_representation.get("id"),
            "pssh": self.pssh,
        }

    async def download_segments(self, output_dir: str = None, concurrent_downloads: int = None, description: str = "DASH"):
        """
        Download segments with parallel workers but concatenate in sequential order.
        Uses sliding window approach: download N segments in parallel, concatenate in order.
        
        Parameters:
            - output_dir (str): Output directory for segments
            - concurrent_downloads (int): Number of concurrent downloads
            - description (str): Description for progress bar
        """
        rep = self.selected_representation
        rep_id = rep['id']
        segment_urls = rep['segment_urls']
        init_url = rep.get('init_url')

        os.makedirs(output_dir or self.tmp_folder, exist_ok=True)
        concat_path = self.get_concat_path(output_dir)

        stream_type = description
        if concurrent_downloads is None:
            worker_type = 'video' if 'Video' in description else 'audio'
            concurrent_downloads = self._get_worker_count(worker_type)

        progress_bar = tqdm(
            total=len(segment_urls) + 1,
            desc=f"Downloading {rep_id}",
            bar_format=self._get_bar_format(stream_type)
        )

        # Initialize estimator
        self.estimator = M3U8_Ts_Estimator(total_segments=len(segment_urls) + 1)

        self.downloaded_segments = {}
        self.failed_segments = set()
        self.info_nFailed = 0
        self.download_interrupted = False
        self.info_nRetry = 0
        self.info_maxRetry = 0

        try:
            timeout_config = httpx.Timeout(SEGMENT_MAX_TIMEOUT, connect=10.0)
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
            
            async with httpx.AsyncClient(timeout=timeout_config, limits=limits) as client:
                with open(concat_path, 'wb') as outfile:
                    await self._download_and_write_init(client, init_url, outfile, progress_bar)
                    await self._download_with_sliding_window(
                        client, segment_urls, outfile, concurrent_downloads, REQUEST_MAX_RETRY, progress_bar
                    )

        except KeyboardInterrupt:
            self.download_interrupted = True
            console.print("\n[red]Download interrupted by user (Ctrl+C).")

        finally:
            progress_bar.close()

        self._verify_download_completion()
        return self._generate_results(stream_type)

    async def _download_and_write_init(self, client, init_url, outfile, progress_bar):
        """
        Download the init segment and write directly to output file.
        """
        seg_type = self._get_segment_url_type()
        
        # Skip init segment for MP4 segment files
        if seg_type == "mp4" and self._has_varying_segment_urls(self.selected_representation.get('segment_urls', [])):
            progress_bar.update(1)
            return
            
        if not init_url:
            return

        try:
            headers = self._merged_headers()
            response = await client.get(init_url, headers=headers, follow_redirects=True)

            if response.status_code == 200:
                outfile.write(response.content)
                if self.estimator:
                    self.estimator.add_ts_file(len(response.content))

            progress_bar.update(1)
            if self.estimator:
                self._throttled_progress_update(len(response.content), progress_bar)

        except Exception as e:
            progress_bar.close()
            raise RuntimeError(f"Error downloading init segment: {e}")

    def _throttled_progress_update(self, content_size: int, progress_bar):
        """
        Throttled progress update to reduce CPU usage.
        """
        current_time = time.time()
        if current_time - self._last_progress_update > self._progress_update_interval:
            if self.estimator:
                self.estimator.update_progress_bar(content_size, progress_bar)
            self._last_progress_update = current_time

    async def _download_with_sliding_window(self, client, segment_urls, outfile, max_workers, max_retry, progress_bar):
        """
        Download segments using sliding window approach:
        - Download max_workers segments in parallel
        - Concatenate in sequential order as they complete
        - Start next download when previous completes
        """
        seg_type = self._get_segment_url_type()
        is_mp4_segments = seg_type == "mp4" and self._has_varying_segment_urls(segment_urls)
        
        total_segments = len(segment_urls)
        next_to_download = 0
        next_to_write = 0
        active_tasks = {}
        
        semaphore = asyncio.Semaphore(max_workers)

        while next_to_write < total_segments and not self.download_interrupted:
            
            # Start new downloads to fill the window
            while next_to_download < total_segments and len(active_tasks) < max_workers:
                idx = next_to_download
                task = asyncio.create_task(
                    self._download_segment_with_retry(client, segment_urls[idx], idx, max_retry, semaphore)
                )
                active_tasks[idx] = task
                next_to_download += 1
            
            if not active_tasks:
                break
            
            # Wait for the NEXT segment we need to write
            if next_to_write in active_tasks:
                task = active_tasks[next_to_write]
                try:
                    success, content, retry_count = await task
                    del active_tasks[next_to_write]
                    
                    # Update stats
                    if retry_count > self.info_maxRetry:
                        self.info_maxRetry = retry_count
                    self.info_nRetry += retry_count
                    
                    if success and content:
                        # Write segment in order
                        if is_mp4_segments:
                            if next_to_write == 0:
                                outfile.write(content)
                            else:
                                for atom in self._extract_moof_mdat_from_bytes(content):
                                    outfile.write(atom)
                        else:
                            outfile.write(content)
                        
                        content_size = len(content)
                        if self.estimator:
                            self.estimator.add_ts_file(content_size)
                            self._throttled_progress_update(content_size, progress_bar)
                    else:
                        self.info_nFailed += 1
                        self.failed_segments.add(next_to_write)
                        console.print(f"[red]Segment {next_to_write} failed after {retry_count} retries")
                    
                    progress_bar.update(1)
                    next_to_write += 1
                    
                except KeyboardInterrupt:
                    self.download_interrupted = True
                    console.print("\n[red]Download interrupted by user (Ctrl+C).")
                    break
            else:
                # Should not happen, but wait a bit
                await asyncio.sleep(0.1)

    async def _download_segment_with_retry(self, client, url, idx, max_retry, semaphore):
        """
        Download a single segment with retry logic.
        
        Returns:
            tuple: (success: bool, content: bytes, retry_count: int)
        """
        async with semaphore:
            headers = self._merged_headers()
            
            for attempt in range(max_retry):
                if self.download_interrupted:
                    return False, None, attempt
                
                try:
                    timeout = min(SEGMENT_MAX_TIMEOUT, 10 + attempt * 3)
                    resp = await client.get(url, headers=headers, follow_redirects=True, timeout=timeout)

                    if resp.status_code == 200:
                        return True, resp.content, attempt
                    elif resp.status_code == 404:
                        console.print(f"[red]Segment {idx} not found (404): {url}")
                        # Don't retry 404 errors
                        return False, None, max_retry
                    else:
                        console.print(f"[yellow]Segment {idx} HTTP {resp.status_code} on attempt {attempt + 1}: {url}")
                        if attempt < max_retry - 1:
                            sleep_time = 0.5 + attempt * 0.5 if attempt < 2 else min(2.0, 1.1 * (2 ** attempt))
                            await asyncio.sleep(sleep_time)
                        
                except Exception as e:
                    console.print(f"[yellow]Segment {idx} error on attempt {attempt + 1}: {e}")
                    if attempt < max_retry - 1:
                        sleep_time = min(2.0, 1.1 * (2 ** attempt))
                        await asyncio.sleep(sleep_time)
            
            return False, None, max_retry

    def _extract_moof_mdat_from_bytes(self, data: bytes):
        """
        Extract only 'moof' and 'mdat' atoms from MP4 bytes.
        Returns a generator of bytes chunks.
        """
        offset = 0
        data_len = len(data)
        
        while offset < data_len:
            if offset + 8 > data_len:
                break
                
            size, atom_type = struct.unpack(">I4s", data[offset:offset+8])
            atom_type = atom_type.decode("ascii", errors="replace")
            
            if size < 8 or offset + size > data_len:
                break
            
            if atom_type in ("moof", "mdat"):
                yield data[offset:offset+size]
            
            offset += size

    def _get_bar_format(self, description: str) -> str:
        """
        Generate platform-appropriate progress bar format.
        """
        return (
            f"{Colors.YELLOW}DASH{Colors.CYAN} {description}{Colors.WHITE}: "
            f"{Colors.MAGENTA}{{bar:40}} "
            f"{Colors.LIGHT_GREEN}{{n_fmt}}{Colors.WHITE}/{Colors.CYAN}{{total_fmt}} {Colors.LIGHT_MAGENTA}TS {Colors.WHITE}"
            f"{Colors.DARK_GRAY}[{Colors.YELLOW}{{elapsed}}{Colors.WHITE} < {Colors.CYAN}{{remaining}}{Colors.DARK_GRAY}] "
            f"{Colors.WHITE}{{postfix}}"
        )

    def _get_worker_count(self, stream_type: str) -> int:
        """
        Calculate optimal parallel workers based on stream type.
        """
        base_workers = {
            'video': DEFAULT_VIDEO_WORKERS,
            'audio': DEFAULT_AUDIO_WORKERS
        }.get(stream_type.lower(), 2)
        return base_workers

    def _generate_results(self, stream_type: str) -> dict:
        """
        Package final download results.
        """
        return {
            'type': stream_type,
            'nFailed': getattr(self, 'info_nFailed', 0),
            'stopped': getattr(self, 'download_interrupted', False)
        }

    def _verify_download_completion(self) -> None:
        """
        Validate final download integrity.
        """
        total = len(self.selected_representation['segment_urls'])

        if self.download_interrupted:
            return
        
        if total == 0:
            return
        
        completion_rate = (total - len(self.failed_segments)) / total if total > 0 else 0
        missing_count = len(self.failed_segments)
        
        if completion_rate >= 0.90 or missing_count <= 30:
            return
        else:
            missing = sorted(self.failed_segments)
            console.print(f"[red]Missing segments: {missing[:10]}..." if len(missing) > 10 else f"[red]Missing segments: {missing}")

        if self.info_nFailed > 0:
            console.print(f" [cyan]Max retries: [red]{self.info_maxRetry} [white]| "
                f"[cyan]Total retries: [red]{self.info_nRetry} [white]| "
                f"[cyan]Failed segments: [red]{self.info_nFailed}")
    
    def get_progress_data(self) -> Dict:
        """Returns current download progress data for API."""
        if not self.estimator:
            return None
            
        total = self.get_segments_count()
        downloaded = total - len(self.failed_segments)
        percentage = (downloaded / total * 100) if total > 0 else 0
        stats = self.estimator.get_stats(downloaded, total)
        
        return {
            'total_segments': total,
            'downloaded_segments': downloaded,
            'failed_segments': self.info_nFailed,
            'current_speed': stats['download_speed'],
            'estimated_size': stats['estimated_total_size'],
            'percentage': round(percentage, 2),
            'eta_seconds': stats['eta_seconds']
        }