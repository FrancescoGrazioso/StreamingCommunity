# 10.01.26

import os
import time
from typing import Generator, Any, Optional, List, Dict


# External library
from rich.console import Console


# Internal utilities
from StreamingCommunity.utils.http_client import fetch


# Logic class
from .models import StreamInfo, DownloadStatusInfo, DownloadStatus, DownloadConfig, MediaTrack
from .wrapper import N_m3u8DLWrapper
from .parser import StreamParser
from .progress import ProgressBarManager, show_streams_table
from .utils import FileUtils


# Variable
console = Console()


class MediaDownloader:
    def __init__(self, url: str, output_dir: str, filename: str, headers: Optional[Dict[str, str]] = None, decryption_keys: Optional[List[str]] = None, external_subtitles: Optional[List[dict]] = None):
        self.url = url
        self.output_dir = output_dir
        self.filename = filename
        self.headers = headers
        self.decryption_keys = decryption_keys
        self.external_subtitles = external_subtitles or []
        
        self.config = DownloadConfig()
        self.status_info = DownloadStatusInfo()
        self.stream_info: Optional[StreamInfo] = None
        
        self.audio_disponibili = 0
        self.audio_selezionati = 0
        self.subtitle_disponibili = 0
        self.subtitle_selezionati = 0
        
        self._current_video_progress = None
        self._current_audio_progress = None
        self._download_start_time = None
        self._is_downloading = False
    
    def configure(self, **kwargs) -> None:
        """Configuration for the downloader"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
    
    def set_keys(self, decryption_keys: Optional[List[str]]) -> None:
        """Update decryption keys for the downloader"""
        self.decryption_keys = decryption_keys
    
    def get_available_streams(self) -> Optional[StreamInfo]:
        """Get information about available streams"""
        if not self.stream_info:
            meta_path = os.path.join(self.output_dir, "temp_analysis", "meta.json")
            
            if os.path.exists(meta_path):
                self.stream_info = StreamParser.parse_stream_info_from_json(meta_path)
            
            if not self.stream_info or not self.stream_info.streams:
                wrapper = N_m3u8DLWrapper(self.config, self.output_dir)
                self.stream_info = wrapper.get_available_streams(self.url, self.headers)
        
        return self.stream_info
    
    def get_streams_json(self) -> Dict[str, Any]:
        """Get available streams in JSON format for GUI"""
        stream_info = self.get_available_streams()
        
        if not stream_info or not stream_info.streams:
            return {"success": False, "error": "No stream info available"}
        
        selected_video = None
        if stream_info.video_streams:
            if self.config.set_resolution == "best":
                selected_video = stream_info.video_streams[0]
            elif self.config.set_resolution == "worst":
                selected_video = stream_info.video_streams[-1]
            elif self.config.set_resolution.endswith("p"):
                target_height = self.config.set_resolution[:-1]
                for stream in stream_info.video_streams:
                    if stream.resolution and target_height in stream.resolution:
                        selected_video = stream
                        break
                if not selected_video:
                    selected_video = stream_info.video_streams[0]
            else:
                selected_video = stream_info.video_streams[0]
        
        audio_langs = self.config.select_audio_lang or []
        subtitle_langs = self.config.select_subtitle_lang or []
        
        streams_data = []
        for stream in stream_info.streams:
            will_download = False
            if stream.type == "Video":
                will_download = (stream == selected_video)
            elif stream.type == "Audio":
                will_download = "all" in [lang.lower() for lang in audio_langs] or "*" in audio_langs or any(
                    lang.lower() == stream.language.lower() or lang.lower() == stream.lang_code.lower() 
                    for lang in audio_langs
                )
            elif stream.type == "Subtitle":
                will_download = "all" in [lang.lower() for lang in subtitle_langs] or "*" in subtitle_langs or any(
                    lang.lower() == stream.language.lower() or lang.lower() == stream.lang_code.lower() 
                    for lang in subtitle_langs
                )
            
            streams_data.append({
                "type": stream.type, 
                "selected": will_download, 
                "resolution": stream.resolution,
                "bitrate": stream.bitrate, 
                "codec": stream.codec, 
                "language": stream.language,
                "lang_code": stream.lang_code if stream.lang_code != "-" else stream.language,
                "language_long": stream.language_long if stream.language_long != "-" else stream.language,
                "variant": stream.variant,
                "encrypted": stream.encrypted, 
                "segments_count": stream.segments_count
            })
        
        return {
            "success": True, 
            "manifest_type": stream_info.manifest_type,
            "total_streams": len(stream_info.streams), 
            "streams": streams_data
        }
    
    def get_download_stats(self) -> Dict[str, Any]:
        """Get real-time download statistics for GUI"""
        if not self._is_downloading:
            return {
                "is_downloading": False, 
                "status": self.status_info.status.value if self.status_info.status else "not_started"
            }
        
        stats = {
            "is_downloading": True, 
            "status": self.status_info.status.value if self.status_info.status else "downloading"
        }
        
        if self._current_video_progress:
            p = self._current_video_progress
            stats["video"] = {
                "percent": min(p.percent, 100.0), 
                "current": p.current, 
                "total": p.total, 
                "speed": p.speed
            }
        
        if self._current_audio_progress:
            p = self._current_audio_progress
            stats["audio"] = {
                "percent": min(p.percent, 100.0), 
                "current": p.current, 
                "total": p.total, 
                "speed": p.speed
            }
        
        return stats
    
    def show_table(self) -> None:
        """Show table with available streams"""
        streams_data = self.get_streams_json()
        if not streams_data["success"]:
            console.print("[red]Unable to retrieve stream information.")
            return
        
        # Count selections for tracking
        self.audio_disponibili = len([s for s in streams_data["streams"] if s["type"] == "Audio"])
        self.audio_selezionati = len([s for s in streams_data["streams"] if s["type"] == "Audio" and s["selected"]])
        self.subtitle_disponibili = len([s for s in streams_data["streams"] if s["type"] == "Subtitle"])
        self.subtitle_selezionati = len([s for s in streams_data["streams"] if s["type"] == "Subtitle" and s["selected"]])
        
        show_streams_table(streams_data, self.external_subtitles)

    def start_download(self, show_progress: bool = True) -> Generator[Dict[str, Any], None, None]:
        """Start the download process, yielding status updates"""
        self.status_info = DownloadStatusInfo()
        self.status_info.status = DownloadStatus.PARSING
        
        # Initialize real-time stats tracking
        self._current_video_progress = None
        self._current_audio_progress = None
        self._download_start_time = time.time()
        self._is_downloading = True
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Apply auto-selection if stream info is available
        if self.stream_info:
            self._apply_smart_selection(self.stream_info)
        
        download_wrapper = N_m3u8DLWrapper(self.config, self.output_dir)
        
        # Progress bar manager
        progress_manager = None
        table_shown = False
        
        try:
            for update in download_wrapper.download(self.url, self.filename, self.headers, self.decryption_keys, self.stream_info):
                self._update_status(update)
                
                if show_progress:
                    if update.get("status") == "parsing" and not table_shown:
                        if "stream_info" in update:
                            table_shown = True
                            self.stream_info = update["stream_info"]
                            console.file.flush()
                    
                    elif update.get("status") == "selected" and not progress_manager:
                        protocol = self.stream_info.manifest_type if self.stream_info else "UNKNOWN"
                        progress_manager = ProgressBarManager(protocol)
                        progress_manager.setup()
                        
                        if self.config.select_audio_lang and self.stream_info:
                            progress_manager.add_audio_task("", self.config.select_audio_lang, self.stream_info)
                    
                    elif update.get("status") == "downloading":
                        if not progress_manager:
                            protocol = self.stream_info.manifest_type if self.stream_info else "UNKNOWN"
                            progress_manager = ProgressBarManager(protocol)
                            progress_manager.setup()
                            
                            if self.config.select_audio_lang and self.stream_info:
                                progress_manager.add_audio_task("", self.config.select_audio_lang, self.stream_info)
                        
                        if "progress_video" in update:
                            self._current_video_progress = update["progress_video"]
                            progress_manager.update_video_progress(update["progress_video"], self.stream_info)
                        
                        if "progress_audio" in update:
                            self._current_audio_progress = update["progress_audio"]
                            progress_manager.update_audio_progress(update["progress_audio"], self.stream_info)
                    
                    elif update.get("status") == "completed":
                        if progress_manager:
                            progress_manager.stop()
                        console.file.flush()
                    
                    elif update.get("status") == "failed":
                        if progress_manager and not update.get("has_404", False):
                            progress_manager.stop()
                        
                        if update.get("has_404", False):
                            console.log("[yellow]404 detected, switching to original URL...")
                        else:
                            console.print(f"[bold red]Download failed: {update.get('error')}")
                        console.file.flush()
                
                yield update
                
                if self.status_info.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED]:
                    break
        
        except KeyboardInterrupt:
            if show_progress and progress_manager:
                progress_manager.stop()
                console.print("\n[yellow]Download cancelled")
            self.status_info.status = DownloadStatus.CANCELLED
            self._is_downloading = False
            raise
        
        except Exception as e:
            if show_progress and progress_manager:
                progress_manager.stop()
            self.status_info.status = DownloadStatus.FAILED
            self.status_info.error_message = str(e)
            self._is_downloading = False
            raise
        
        finally:
            self._is_downloading = False
    
    def _apply_smart_selection(self, stream_info: StreamInfo):
        """Smart selection of audio and subtitle languages based on available streams"""
        audio_langs = [lang.lower() for lang in (self.config.select_audio_lang or [])]
        subtitle_langs = [lang.lower() for lang in (self.config.select_subtitle_lang or [])]
        
        available_audio_langs = set()
        available_subtitle_langs = set()
        
        for stream in stream_info.audio_streams:
            if stream.language and stream.language != "-":
                available_audio_langs.add(stream.language.lower())
            if stream.lang_code and stream.lang_code != "-":
                available_audio_langs.add(stream.lang_code.lower())
        
        for stream in stream_info.subtitle_streams:
            if stream.language and stream.language != "-":
                available_subtitle_langs.add(stream.language.lower())
            if stream.lang_code and stream.lang_code != "-":
                available_subtitle_langs.add(stream.lang_code.lower())
        
        if stream_info.audio_streams:
            if not audio_langs or "all" in audio_langs or "*" in audio_langs:
                self.config.select_audio_lang = list(available_audio_langs)
            else:
                matched_audio = [lang for lang in audio_langs if lang in available_audio_langs]
                
                if not matched_audio:
                    first_audio = stream_info.audio_streams[0]
                    fallback_lang = first_audio.lang_code if first_audio.lang_code != "-" else first_audio.language
                    self.config.select_audio_lang = [fallback_lang]
                    console.log(f"[yellow]No matching audio found, auto-selecting: {fallback_lang}")
                else:
                    self.config.select_audio_lang = matched_audio
        
        if stream_info.subtitle_streams:
            if not subtitle_langs or "all" in subtitle_langs or "*" in subtitle_langs:
                self.config.select_subtitle_lang = list(available_subtitle_langs)
            else:
                matched_subtitles = [lang for lang in subtitle_langs if lang in available_subtitle_langs]
                
                if not matched_subtitles:
                    first_subtitle = stream_info.subtitle_streams[0]
                    fallback_lang = first_subtitle.lang_code if first_subtitle.lang_code != "-" else first_subtitle.language
                    self.config.select_subtitle_lang = [fallback_lang]
                    console.log(f"[yellow]No matching subtitles found, auto-selecting: {fallback_lang}")
                else:
                    self.config.select_subtitle_lang = matched_subtitles
        
    def _update_status(self, update: Dict[str, Any]) -> None:
        """Update internal status based on the update"""
        status = update.get("status")
        
        if status == "parsing":
            self.status_info.status = DownloadStatus.PARSING
            if "stream_info" in update:
                self.stream_info = update["stream_info"]

        elif status in ["selected", "downloading"]:
            self.status_info.status = DownloadStatus.DOWNLOADING

        elif status == "completed":
            self.status_info.status = DownloadStatus.COMPLETED
            self.status_info.is_completed = True
            self._is_downloading = False
            result = update.get("result")
            if result:
                self._process_completed_download(result)

        elif status == "failed":
            if not update.get("has_404", False):
                self.status_info.status = DownloadStatus.FAILED
                self.status_info.error_message = update.get("error")
                self._is_downloading = False

        elif status == "cancelled":
            self.status_info.status = DownloadStatus.CANCELLED
            self._is_downloading = False
    
    def _build_language_mapping(self) -> Dict[str, str]:
        """Build mapping from original Language field (used in filenames) to display name."""
        mapping = {}
        
        if not self.stream_info:
            return mapping
        
        for stream in self.stream_info.streams:
            if stream.type not in ["Audio", "Subtitle"]:
                continue

            # Use original_language (from meta.json) as key, since N_m3u8DL-RE uses it in filenames
            original_lang = stream.original_language if stream.original_language else stream.language
            lang_code_display = stream.lang_code if stream.lang_code != "-" else stream.language
            lang_long = stream.language_long if stream.language_long != "-" else stream.language
            
            if stream.variant:
                display_name = f"{lang_code_display} - {lang_long} - {stream.variant}"
            else:
                display_name = f"{lang_code_display} - {lang_long}"
            
            mapping[original_lang.lower()] = display_name
        
        return mapping
    
    def _process_completed_download(self, result):
        """Process downloaded files and download external subtitles"""
        self.status_info.video_path = result.video_path
        language_mapping = self._build_language_mapping()
        
        # Process audio tracks
        self.status_info.audios_paths = []
        for track in result.audio_tracks:
            lang_code = track.language.lower()
            display_name = language_mapping.get(lang_code, track.language)
            
            self.status_info.audios_paths.append({
                "path": track.path,
                "language": display_name
            })
        
        # Process subtitle tracks
        all_subtitles = list(result.subtitle_tracks)
        
        if self.external_subtitles and self.config.select_subtitle_lang:
            filtered_externals = [
                ext_sub for ext_sub in self.external_subtitles
                if any(lang.lower() in ext_sub.get('language', '').lower() 
                      for lang in self.config.select_subtitle_lang)
            ]
            
            if filtered_externals:
                external_subs = self._download_external_subtitles(filtered_externals)
                all_subtitles.extend(external_subs)
        
        self.status_info.subtitle_paths = []
        for track in all_subtitles:
            lang_code = track.language.lower()
            display_name = language_mapping.get(lang_code, track.language)
            
            self.status_info.subtitle_paths.append({
                "path": track.path,
                "language": display_name,
                "format": getattr(track, 'format', None)
            })
    
    def _download_external_subtitles(self, external_subtitles: List[dict]) -> List[MediaTrack]:
        """Download external subtitles from URLs"""
        downloaded_subs = []
        
        for sub_info in external_subtitles:
            url = sub_info.get('url')
            language = sub_info.get('language', 'unknown')
            format_ext = sub_info.get('format', 'srt')
            
            try:
                sub_filename = f"{self.filename}.{language}.{format_ext}"
                sub_path = os.path.join(self.output_dir, sub_filename)
                console.print(f"\n[cyan]Download ext sub: [yellow]{language}.{format_ext}")
                
                response_text = fetch(url, headers=self.headers)
                if response_text is None:
                    raise Exception("Failed to download subtitle")
                
                with open(sub_path, 'w', encoding='utf-8') as f:
                    f.write(response_text)
                
                downloaded_subs.append(MediaTrack(
                    path=str(sub_path),
                    language=language,
                    format=format_ext
                ))

            except Exception as e:
                print(f"Error downloading subtitle {url}: {e}")
                continue
        
        return downloaded_subs
    
    def get_status(self) -> DownloadStatusInfo:
        """Get current download status"""
        if (self.status_info.is_completed and not self.status_info.video_path and not self.status_info.audios_paths):
            audio_lang_param = None
            if self.config.select_audio_lang:
                if "all" in [lang.lower() for lang in self.config.select_audio_lang] or "*" in self.config.select_audio_lang:
                    audio_lang_param = None
                else:
                    audio_lang_param = self.config.select_audio_lang[0] if isinstance(self.config.select_audio_lang, list) else self.config.select_audio_lang
            
            subtitle_lang_param = None
            if self.config.select_subtitle_lang:
                if "all" in [lang.lower() for lang in self.config.select_subtitle_lang] or "*" in self.config.select_subtitle_lang:
                    subtitle_lang_param = None
                else:
                    subtitle_lang_param = self.config.select_subtitle_lang[0] if isinstance(self.config.select_subtitle_lang, list) else self.config.select_subtitle_lang
            
            result = FileUtils.find_downloaded_files(
                self.output_dir, self.filename,
                audio_lang_param,
                subtitle_lang_param
            )
            
            if result:
                self._process_completed_download(result)
        
        return self.status_info