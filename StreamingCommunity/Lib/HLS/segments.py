# 18.04.24

import os
import time
import logging
import binascii
import asyncio
from urllib.parse import urljoin, urlparse
from typing import Dict, Optional


# External libraries
import httpx
from tqdm import tqdm
from rich.console import Console


# Internal utilities
from StreamingCommunity.Util import config_manager, Colors
from StreamingCommunity.Util.http_client import create_client_curl, get_userAgent
from StreamingCommunity.Util.os import get_wvd_path


# Logic class
from .decrypt import M3U8_Decryption
from .estimator import M3U8_Ts_Estimator
from .parser import M3U8_Parser
from .url_fixer import M3U8_UrlFix


# External
from ..MP4 import MP4_Downloader
from ..DASH.extractor import get_widevine_keys
from ..DASH.decrypt import decrypt_with_mp4decrypt


# Config
console = Console()
REQUEST_MAX_RETRY = config_manager.config.get_int('REQUESTS', 'max_retry')
REQUEST_VERIFY = config_manager.config.get_bool('REQUESTS', 'verify')
DEFAULT_VIDEO_WORKERS = config_manager.config.get_int('M3U8_DOWNLOAD', 'default_video_workers')
DEFAULT_AUDIO_WORKERS = config_manager.config.get_int('M3U8_DOWNLOAD', 'default_audio_workers')
MAX_TIMEOUT = config_manager.config.get_int("REQUESTS", "timeout")
SEGMENT_MAX_TIMEOUT = config_manager.config.get_int("M3U8_DOWNLOAD", "segment_timeout")
ENABLE_RETRY = config_manager.config.get_bool('M3U8_DOWNLOAD', 'enable_retry')


class M3U8_Segments:
    def __init__(self, url: str, tmp_folder: str, license_url: Optional[str] = None, is_index_url: bool = True, custom_headers: Optional[Dict[str, str]] = None):
        """
        Initializes the M3U8_Segments object.

        Parameters:
            - url (str): The URL of the M3U8 playlist.
            - tmp_folder (str): The temporary folder to store downloaded segments.
            - is_index_url (bool): Flag indicating if url is a URL (default True).
            - custom_headers (Dict[str, str]): Optional custom headers to use for all requests.
        """
        self.url = url
        self.tmp_folder = tmp_folder
        self.license_url = license_url
        self.is_index_url = is_index_url
        self.custom_headers = custom_headers if custom_headers else {'User-Agent': get_userAgent()}
        self.final_output_path = os.path.join(self.tmp_folder, "0.ts")
        self.drm_method = None
        os.makedirs(self.tmp_folder, exist_ok=True)
        self.enable_retry = ENABLE_RETRY

        # Util class
        self.decryption: M3U8_Decryption = None 
        self.class_ts_estimator = M3U8_Ts_Estimator(0, self) 
        self.class_url_fixer = M3U8_UrlFix(url)

        # Stats
        self.downloaded_segments = set()
        self.failed_segments = set()
        self.download_interrupted = False
        self.info_maxRetry = 0
        self.info_nRetry = 0
        self.info_nFailed = 0

        # Progress throttling
        self._last_progress_update = 0
        self._progress_update_interval = 0.1

    def __get_key__(self, m3u8_parser: M3U8_Parser) -> bytes:
        """
        Fetches the encryption key from the M3U8 playlist.
        """
        if m3u8_parser.keys.get('drm') is None:
            key_uri = urljoin(self.url, m3u8_parser.keys.get('uri'))
            parsed_url = urlparse(key_uri)
            self.key_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"

            try:
                response = create_client_curl(headers=self.custom_headers).get(key_uri)
                response.raise_for_status()

                hex_content = binascii.hexlify(response.content).decode('utf-8')
                console.log(f"[cyan]Fetch key from URI: [green]{key_uri}")
                return bytes.fromhex(hex_content)
                
            except Exception as e:
                raise Exception(f"Failed to fetch key: {e}")
            
        else:
            self.drm_method = m3u8_parser.keys.get('method')
            logging.info("DRM key detected, method: " + str(m3u8_parser.keys.get('method')))
        
    def parse_data(self, m3u8_content: str) -> None:
        """Parses the M3U8 content and extracts necessary data."""
        m3u8_parser = M3U8_Parser()
        m3u8_parser.parse_data(uri=self.url, raw_content=m3u8_content)

        self.expected_real_time_s = m3u8_parser.duration
        self.segment_init_url = m3u8_parser.init_segment
        self.has_init_segment = self.segment_init_url is not None

        if m3u8_parser.keys:
            key = self.__get_key__(m3u8_parser)
            self.decryption = M3U8_Decryption(key, m3u8_parser.keys.get('iv'), m3u8_parser.keys.get('method'), m3u8_parser.keys.get('pssh'))

        segments = [
            self.class_url_fixer.generate_full_url(seg) if "http" not in seg else seg
            for seg in m3u8_parser.segments
        ]
        self.segments = segments
        self.stream_type = self.get_type_stream(self.segments)
        self.class_ts_estimator.total_segments = len(self.segments)
        console.log(f"[cyan]Detected stream type: [green]{str(self.stream_type).upper()}")
        
    def get_segments_count(self) -> int:
        """
        Returns the total number of segments.
        """
        return len(self.segments) if hasattr(self, 'segments') else 0
    
    def get_type_stream(self, segments) -> str:
        self.is_stream_ts = (".ts" in self.segments[len(self.segments) // 2]) if self.segments else False
        self.is_stream_mp4 = (".mp4" in self.segments[len(self.segments) // 2]) if self.segments else False
        self.is_stream_aac = (".aac" in self.segments[len(self.segments) // 2]) if self.segments else False

        if self.is_stream_ts:
            return "ts"
        elif self.is_stream_mp4:
            return "mp4"
        elif self.is_stream_aac:
            return "aac"
        else:
            console.log("[yellow]Warning: Unable to determine stream type.")
            return "ts"

    def get_info(self) -> None:
        """
        Retrieves M3U8 playlist information from the given URL.
        """
        if self.is_index_url:
            response = create_client_curl(headers=self.custom_headers).get(self.url)
            response.raise_for_status()
            
            self.parse_data(response.text)
            with open(os.path.join(self.tmp_folder, "playlist.m3u8"), "w", encoding='utf-8') as f:
                f.write(response.text)
                    
    def _throttled_progress_update(self, content_size: int, progress_bar: tqdm):
        """
        Throttled progress update to reduce CPU usage.
        """
        current_time = time.time()
        if current_time - self._last_progress_update > self._progress_update_interval:
            self.class_ts_estimator.update_progress_bar(content_size, progress_bar)
            self._last_progress_update = current_time

    async def _download_and_write_init(self, client: httpx.AsyncClient, outfile, progress_bar: tqdm) -> bool:
        """
        Downloads the initialization segment and writes directly to output file.
        """
        if not self.has_init_segment:
            return False
            
        init_url = self.segment_init_url
        if not init_url.startswith("http"):
            init_url = self.class_url_fixer.generate_full_url(init_url)
            
        try:
            response = await client.get(init_url, timeout=SEGMENT_MAX_TIMEOUT, headers=self.custom_headers)
            response.raise_for_status()
            init_content = response.content
            
            # Decrypt if needed
            if self.decryption is not None:
                try:
                    init_content = self.decryption.decrypt(init_content)
                except Exception as e:
                    logging.error(f"Decryption failed for init segment: {str(e)}")
                    return False
            
            # Write init segment directly to output file
            outfile.write(init_content)
            
            progress_bar.update(1)
            self._throttled_progress_update(len(init_content), progress_bar)
            logging.info("Init segment downloaded successfully")
            return True
            
        except Exception as e:
            logging.error(f"Failed to download init segment: {str(e)}")
            return False

    async def _download_segment_with_retry(self, client: httpx.AsyncClient, url: str, idx: int, max_retry: int, semaphore: asyncio.Semaphore) -> tuple:
        """
        Downloads a single TS segment with retry logic.

        Returns:
            tuple: (success: bool, content: bytes, retry_count: int)
        """
        async with semaphore:
            for attempt in range(max_retry):
                if self.download_interrupted:
                    return False, None, attempt
                
                try:
                    timeout = min(SEGMENT_MAX_TIMEOUT, 10 + attempt * 5)
                    response = await client.get(url, timeout=timeout, headers=self.custom_headers, follow_redirects=True)
                    response.raise_for_status()
                    segment_content = response.content

                    # Decrypt if needed
                    if self.decryption is not None:
                        try:
                            segment_content = self.decryption.decrypt(segment_content)
                        except Exception as e:
                            logging.error(f"Decryption failed for segment {idx}: {str(e)}")
                            if attempt + 1 == max_retry:
                                return False, None, attempt
                            raise e

                    return True, segment_content, attempt

                except Exception:
                    if attempt + 1 == max_retry:
                        console.print(f" -- [red]Failed request for segment: {idx}")
                        return False, None, max_retry
                    
                    sleep_time = 0.5 + attempt * 0.5 if attempt < 2 else min(3.0, 1.02 ** attempt)
                    await asyncio.sleep(sleep_time)
            
            return False, None, max_retry

    async def _download_with_sliding_window(self, client: httpx.AsyncClient, outfile, max_workers: int, progress_bar: tqdm):
        """
        Download segments using sliding window approach:
        - Download max_workers segments in parallel
        - Concatenate in sequential order (1→2→3→N)
        - Start next download when previous completes
        """
        total_segments = len(self.segments)
        next_to_download = 0
        next_to_write = 0
        active_tasks = {}
        
        semaphore = asyncio.Semaphore(max_workers)

        while next_to_write < total_segments and not self.download_interrupted:
            
            # Start new downloads to fill the window
            while next_to_download < total_segments and len(active_tasks) < max_workers:
                idx = next_to_download
                task = asyncio.create_task(
                    self._download_segment_with_retry(client, self.segments[idx], idx, REQUEST_MAX_RETRY, semaphore)
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
                        # Write segment in sequential order
                        outfile.write(content)
                        self.downloaded_segments.add(next_to_write)
                        
                        content_size = len(content)
                        self.class_ts_estimator.add_ts_file(content_size)
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

    async def download_segments_async(self, description: str, type: str):
        """
        Downloads all TS segments with parallel workers but sequential concatenation.

        Parameters:
            - description: Description to insert on tqdm bar
            - type (str): Type of download: 'video' or 'audio'
        """
        self.get_info()

        if self.stream_type in ["ts", "aac"]:

            # Initialize progress bar
            total_segments = len(self.segments) + (1 if self.has_init_segment else 0)
            progress_bar = tqdm(
                total=total_segments,
                bar_format=self._get_bar_format(description)
            )

            # Reset stats
            self.downloaded_segments = set()
            self.failed_segments = set()
            self.info_nFailed = 0
            self.info_nRetry = 0
            self.info_maxRetry = 0
            self.download_interrupted = False

            try:
                # Configure HTTP client
                timeout_config = httpx.Timeout(SEGMENT_MAX_TIMEOUT, connect=10.0)
                limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
                
                async with httpx.AsyncClient(timeout=timeout_config, limits=limits, verify=REQUEST_VERIFY) as client:
                    
                    # Open output file ONCE for entire download
                    with open(self.final_output_path, 'wb') as outfile:
                        
                        # Download init segment first
                        await self._download_and_write_init(client, outfile, progress_bar)
                        
                        # Update estimator
                        self.class_ts_estimator.total_segments = len(self.segments)
                        
                        # Determine worker count
                        max_workers = self._get_worker_count(type)
                        
                        # Download with sliding window (parallel download, sequential write)
                        await self._download_with_sliding_window(client, outfile, max_workers, progress_bar)

            except KeyboardInterrupt:
                self.download_interrupted = True
                console.print("\n[red]Download interrupted by user (Ctrl+C).")
                
            finally:
                progress_bar.close()
                self._display_final_stats()

            return self._generate_results(type)
        
        else:
            # DRM
            if self.decryption is not None:

                # Get Widevine keys
                content_keys = get_widevine_keys(self.decryption.pssh, self.license_url, get_wvd_path())

                # Download encrypted MP4 file
                encrypted_file, kill = MP4_Downloader(
                    url = self.segments[0],
                    path=os.path.join(self.tmp_folder, "encrypted.mp4"),
                    headers_=self.custom_headers,
                    show_final_info=False
                )

                # Decrypt MP4 file
                KID = content_keys[0]['kid']
                KEY = content_keys[0]['key']
                decrypted_file = os.path.join(self.tmp_folder, f"{type}_decrypted.mp4")
                mp4_output = decrypt_with_mp4decrypt("MP4", encrypted_file, KID, KEY, decrypted_file)
                
                return self._generate_results(type, mp4_output)
            
            # NOT DRM
            else:
                if len(self.segments) == 0:
                    console.print("[red]No segments found to download.")
                    return self._generate_results(type)
                
                decrypted_file, kill = MP4_Downloader(
                    url = self.segments[0],
                    path=os.path.join(self.tmp_folder, f"{type}_decrypted.mp4"),
                    headers_=self.custom_headers,
                    show_final_info=False
                )
                return self._generate_results(type, decrypted_file)

    def download_streams(self, description: str, type: str):
        """
        Synchronous wrapper for download_segments_async.

        Parameters:
            - description: Description to insert on tqdm bar
            - type (str): Type of download: 'video' or 'audio'
        """
        try:
            return asyncio.run(self.download_segments_async(description, type))
        
        except KeyboardInterrupt:
            self.download_interrupted = True
            console.print("\n[red]Download interrupted by user (Ctrl+C).")
            return self._generate_results(type)

    def _get_bar_format(self, description: str) -> str:
        """Generate platform-appropriate progress bar format."""
        return (
            f"{Colors.YELLOW}HLS{Colors.CYAN} {description}{Colors.WHITE}: "
            f"{Colors.MAGENTA}{{bar:40}} "
            f"{Colors.LIGHT_GREEN}{{n_fmt}}{Colors.WHITE}/{Colors.CYAN}{{total_fmt}} {Colors.LIGHT_MAGENTA}TS {Colors.WHITE}"
            f"{Colors.DARK_GRAY}[{Colors.YELLOW}{{elapsed}}{Colors.WHITE} < {Colors.CYAN}{{remaining}}{Colors.DARK_GRAY}] "
            f"{Colors.WHITE}{{postfix}}"
        )
    
    def _get_worker_count(self, stream_type: str) -> int:
        """Return parallel workers based on stream type."""
        return {
            'video': DEFAULT_VIDEO_WORKERS,
            'audio': DEFAULT_AUDIO_WORKERS
        }.get(stream_type.lower(), 1)
    
    def _generate_results(self, stream_type: str, output_path: str = None) -> Dict:
        """Package final download results."""
        return {
            'type': stream_type,
            'nFailed': self.info_nFailed,
            'stopped': self.download_interrupted,
            'stream': self.stream_type,
            'drm': self.drm_method,
            'output_path': output_path if output_path else self.final_output_path
        }

    def _display_final_stats(self) -> None:
        """Display final download statistics."""
        if self.info_nFailed > 0:
            console.log(f"[cyan]Max retries: [red]{self.info_maxRetry} [white] | "
                f"[cyan]Total retries: [red]{self.info_nRetry} [white] | "
                f"[cyan]Failed segments: [red]{self.info_nFailed}")
            
            if self.failed_segments:
                missing = sorted(self.failed_segments)
                console.print(f"[red]Failed segment indices: {missing[:10]}..." if len(missing) > 10 else f"[red]Failed segment indices: {missing}")
        
    def get_progress_data(self) -> Dict:
        """Returns current download progress data for API consumption."""
        total = self.get_segments_count()
        downloaded = len(self.downloaded_segments)
        percentage = (downloaded / total * 100) if total > 0 else 0
        stats = self.class_ts_estimator.get_stats(downloaded, total)
        
        return {
            'total_segments': total,
            'downloaded_segments': downloaded,
            'failed_segments': self.info_nFailed,
            'current_speed': stats['download_speed'],
            'estimated_size': stats['estimated_total_size'],
            'percentage': round(percentage, 2),
            'eta_seconds': stats['eta_seconds']
        }