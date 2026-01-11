# 10.01.26

import re
import time
from typing import Dict, Any, Optional


# External libraries
from rich.console import Console
from rich.progress import Progress, TextColumn
from rich.table import Table


# Logic
from .utils import CustomBarColumn, FormatUtils
from .parser import StreamParser


# Variable
console = Console()


class ProgressBarManager:
    def __init__(self, manifest_type: str = "UNKNOWN"):
        self.manifest_type = manifest_type
        self.progress_bars: Optional[Progress] = None
        self.tasks: Dict[str, Any] = {}                         # Single dict for all tasks
        self.start_times: Dict[str, float] = {}
        self.last_values: Dict[str, tuple[str, float]] = {}     # (size, elapsed)
        self.stream_info: Any = None                            # Store stream_info for key normalization
    
    @staticmethod
    def _extract_stream_key(progress_data: Any, stream_info: Any = None) -> str:
        """Extract unique key from DownloadProgress: 'Vid' -> 'video', 'Aud-ita' -> 'aud-ita', 'Sub-ita-forced' -> 'sub-ita-forced'"""
        stream_type = progress_data.stream_type.lower()  # Vid -> vid, Aud -> aud, Sub -> sub
        
        if stream_type == "vid":
            return "video"
        
        desc = progress_data.description
        parts = [p.strip() for p in desc.split('|')]
        
        lang_part = ""
        name_part = ""
        
        if len(parts) == 2:
            lang_part = parts[0]
            name_part = parts[1]
        elif len(parts) >= 3:
            for part in parts:
                if re.search(r'\d+\s*[KMG]?BPS', part, re.IGNORECASE):
                    continue
                if re.search(r'\d+x\d+', part):
                    continue
                if part.lower() in ['main', 'high', 'baseline']:
                    continue
                if not lang_part:
                    lang_part = part
                elif not name_part:
                    name_part = part
        else:
            lang_part = parts[0] if parts else ""
        
        # Extract variant from both parts
        lang_from_desc, variant_from_code = StreamParser._extract_variant_from_language(lang_part)
        _, variant_from_name = StreamParser._extract_variant_from_name(name_part) if name_part else ("", "")
        variant = variant_from_name if variant_from_name else variant_from_code
        
        lang = lang_from_desc.lower()
        if stream_info:
            if stream_type == "aud":
                for stream in stream_info.audio_streams:
                    if (lang == stream.lang_code.lower() or lang == stream.language.lower() or lang == (stream.language_long.lower() if stream.language_long != "-" else "")):
                        if stream.original_language and variant and variant.lower() in stream.original_language.lower():
                            return f"{stream_type}-{stream.original_language.lower()}"
                        
                        # Use original_language if available for consistency
                        if stream.original_language:
                            return f"{stream_type}-{stream.original_language.lower()}"
                        
                        lang = stream.lang_code.lower()
                        break

            elif stream_type == "sub":
                for stream in stream_info.subtitle_streams:
                    if (lang == stream.lang_code.lower() or lang == stream.language.lower() or lang == (stream.language_long.lower() if stream.language_long != "-" else "")):
                        
                        # Check if variant matches
                        variant_matches = False
                        if stream.variant and variant:
                            variant_matches = stream.variant.lower() == variant.lower()
                        elif not stream.variant and not variant:
                            variant_matches = True
                        
                        if variant_matches:
                            # Use original_language to get the exact key (e.g., "ita-forced" not just "ita")
                            if stream.original_language:
                                return f"{stream_type}-{stream.original_language.lower()}"
                            break
        
        # Fallback to constructed key
        if variant:
            return f"{stream_type}-{lang}-{variant.lower()}"
        return f"{stream_type}-{lang}"
    
    @staticmethod
    def _make_display_name(progress_data: Any, stream_info: Any = None) -> str:
        """Create display name from DownloadProgress using stream_info data"""
        stream_type = progress_data.stream_type
        
        if stream_type == "Vid":
            return "[cyan]Video[/cyan]"
        
        # If no stream_info, fallback to basic display
        if not stream_info:
            return f"[cyan]{stream_type}[/cyan]"
        
        # Extract language from description (clean bitrate/resolution info first)
        desc = progress_data.description
        desc = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', desc)
        desc = re.sub(r'[━╸╺─\]]+', '', desc).strip()
        parts = [p.strip() for p in desc.split('|')]
        
        lang_part = ""
        for part in parts:
            if re.search(r'\d+\s*[KMG]?BPS', part, re.IGNORECASE):
                continue
            if re.search(r'\d+x\d+', part):
                continue
            if part.lower() in ['main', 'high', 'baseline']:
                continue
            lang_part = part
            break
        
        if not lang_part:
            lang_part = parts[0] if parts else ""
        
        lang_from_desc, _ = StreamParser._extract_variant_from_language(lang_part.strip())
        lang_from_desc = lang_from_desc.lower()
        
        # Find matching stream in stream_info to get Lang, Lang_L, Variant
        streams = stream_info.audio_streams if stream_type == "Aud" else stream_info.subtitle_streams
        
        for stream in streams:
            if (lang_from_desc == stream.lang_code.lower() or lang_from_desc == stream.language.lower() or lang_from_desc == (stream.language_long.lower() if stream.language_long != "-" else "")):
                
                # Use stream data: Lang, Lang_L, Variant
                lang_code = stream.lang_code
                lang_long = stream.language_long if stream.language_long != "-" else stream.language
                variant = stream.variant
                
                if stream_type == "Aud":
                    variant_str = f" - {variant}" if variant else ""
                    return f"[cyan]Audio[/cyan] [bright_magenta][{lang_code.upper()} - {lang_long}{variant_str}][/bright_magenta]"
                else:  # Sub
                    variant_str = f" - {variant}" if variant else ""
                    return f"[cyan]Subtitle[/cyan] [bright_magenta][{lang_code.upper()} - {lang_long}{variant_str}][/bright_magenta]"
        
        # Fallback if no match found
        return f"[cyan]{stream_type}[/cyan] [bright_magenta][{lang_from_desc.upper()}][/bright_magenta]"
    
    def setup(self) -> None:
        """Initialize progress bars"""
        self.progress_bars = Progress(
            TextColumn("[bold]{task.description}[/bold]"),
            CustomBarColumn(bar_width=40),
            TextColumn("[bright_green]{task.fields[current]}[/bright_green][dim]/[/dim][bright_cyan]{task.fields[total_segments]}[/bright_cyan]"),
            TextColumn("[dim]\\[[/dim][bright_yellow]{task.fields[elapsed]}[/bright_yellow][dim] < [/dim][bright_cyan]{task.fields[eta]}[/bright_cyan][dim]][/dim]"),
            TextColumn("[bright_green]{task.fields[size_value]}[/bright_green] [bright_magenta]{task.fields[size_unit]}[/bright_magenta]"),
            TextColumn("[dim]@[/dim]"),
            TextColumn("[bright_cyan]{task.fields[speed_value]}[/bright_cyan] [bright_magenta]{task.fields[speed_unit]}[/bright_magenta]"),
            console=console
        )
        self.progress_bars.start()
        
        # Add video task
        task = self.progress_bars.add_task(
            f"[orange1]{self.manifest_type}[/orange1] [cyan]Video[/cyan]",
            total=100,
            current="0", total_segments="0",
            elapsed="00:00", eta="00:00",
            size_value="0.00", size_unit="MB",
            speed_value="0.00", speed_unit="MB/s"
        )
        self.tasks["video"] = task
        self.start_times["video"] = time.time()
        self.last_values["video"] = ("0.00 MB", 0.0)
    
        self.start_times["video"] = time.time()
        self.last_values["video"] = ("0.00 MB", 0.0)
    
    def add_audio_task(self, language: str, audio_langs: list, stream_info: Any = None) -> None:
        """Add audio tasks - called before download starts"""
        if not self.progress_bars or not stream_info:
            return
        
        self.stream_info = stream_info
        
        for stream in stream_info.audio_streams:
            lang_code = stream.lang_code.lower()
            lang_long = stream.language_long if stream.language_long != "-" else stream.language
            
            if "all" in [l.lower() for l in audio_langs] or "*" in audio_langs or lang_code in [l.lower() for l in audio_langs]:
                # Use original_language if available to match filename-based keys
                if stream.original_language:
                    key = f"aud-{stream.original_language.lower()}"
                else:
                    key = f"aud-{lang_code}"
                
                if key not in self.tasks:
                    # Use segments_count from stream_info if available, otherwise let it update dynamically
                    total_segs = str(stream.segments_count) if stream.segments_count and stream.segments_count > 0 else "-"
                    
                    variant_str = f" - {stream.variant}" if stream.variant else ""
                    
                    task = self.progress_bars.add_task(
                        f"[orange1]{self.manifest_type}[/orange1] [cyan]Audio[/cyan] [bright_magenta][{lang_code.upper()} - {lang_long}{variant_str}][/bright_magenta]",
                        total=100,
                        current="0", total_segments=total_segs,
                        elapsed="00:00", eta="00:00",
                        size_value="0.00", size_unit="MB",
                        speed_value="0.00", speed_unit="MB/s"
                    )
                    self.tasks[key] = task
                    self.start_times[key] = time.time()
                    self.last_values[key] = ("0.00 MB", 0.0)
    
    def update_video_progress(self, progress_data: Any, stream_info: Any = None) -> None:
        """Update video progress - uses DownloadProgress object"""
        self._update_any_progress(progress_data, stream_info)
    
    def update_audio_progress(self, progress_data: Any, stream_info: Any = None) -> None:
        """Update audio progress - uses DownloadProgress object"""
        self._update_any_progress(progress_data, stream_info)
    
    def _update_any_progress(self, progress_data: Any, stream_info: Any = None) -> None:
        """Generic update for any stream type using DownloadProgress"""
        if not self.progress_bars:
            return
        
        # Skip subtitle progress updates (subtitles download silently)
        if progress_data.stream_type.lower() == "sub":
            return
        
        # Use passed stream_info or fallback to self.stream_info
        active_stream_info = stream_info if stream_info else self.stream_info
        
        # Get or create task
        key = self._extract_stream_key(progress_data, active_stream_info)
        if key not in self.tasks:
            display_name = self._make_display_name(progress_data, active_stream_info)
            task = self.progress_bars.add_task(
                f"[orange1]{self.manifest_type}[/orange1] {display_name}",
                total=100,
                current="0", total_segments="0",
                elapsed="00:00", eta="00:00",
                size_value="0.00", size_unit="MB",
                speed_value="0.00", speed_unit="MB/s"
            )
            self.tasks[key] = task
            self.start_times[key] = time.time()
            self.last_values[key] = ("0.00 MB", 0.0)
        
        task_id = self.tasks[key]
        start_time = self.start_times[key]
        last_size, last_elapsed = self.last_values[key]
        
        # Calculate progress
        p = progress_data
        elapsed = time.time() - start_time
        eta = FormatUtils.calculate_eta(p.current, p.total, elapsed) if p.percent < 99.5 else 0
        
        size_str = FormatUtils.parse_size_to_mb(p.total_size)
        size_parts = size_str.rsplit(' ', 1)
        
        # Store last valid values
        if p.percent < 99.5 and len(size_parts) == 2 and size_parts[0] != "0.00":
            last_size = size_str
            last_elapsed = elapsed
            self.last_values[key] = (last_size, last_elapsed)
        
        # Use stored values when Done
        if p.percent >= 99.5:
            final_size_parts = last_size.rsplit(' ', 1)
            final_elapsed = last_elapsed
        else:
            final_size_parts = size_parts
            final_elapsed = elapsed
        
        speed_value = "Done" if p.percent >= 99.5 else FormatUtils.parse_speed_to_mb(p.speed).split()[0]
        speed_unit = "" if p.percent >= 99.5 else "MB/s"
        
        try:
            self.progress_bars.update(
                task_id,
                completed=min(p.percent, 100.0),
                current=str(p.current),
                total_segments=str(p.total),
                elapsed=FormatUtils.format_time(final_elapsed),
                eta=FormatUtils.format_time(eta),
                size_value=final_size_parts[0] if len(final_size_parts) == 2 else "0.00",
                size_unit=final_size_parts[1] if len(final_size_parts) == 2 else "MB",
                speed_value=speed_value,
                speed_unit=speed_unit
            )
            self.progress_bars.refresh()
        except Exception:
            pass
    
    def stop(self) -> None:
        """Stop and cleanup progress bars"""
        if self.progress_bars:
            self.progress_bars.stop()
            self.progress_bars = None


def show_streams_table(streams_data: Dict[str, Any], external_subtitles: list = None) -> None:
    """Show table with available streams"""
    if not streams_data.get("success"):
        console.print("[red]Unable to retrieve stream information.")
        return
    
    table = Table()
    table.add_column("Type", style="bright_cyan")
    table.add_column("Sel", style="bold bright_green", justify="center")
    table.add_column("Resolution", style="bright_yellow")
    table.add_column("Bitrate", style="bright_white")
    table.add_column("Codec", style="bright_green")
    table.add_column("Lang", style="bright_magenta")
    table.add_column("Lang_L", style="bright_blue")
    table.add_column("Variant", style="bright_yellow")
    table.add_column("Duration", style="bright_white")
    table.add_column("Segments", style="bright_cyan", justify="right")
    
    for stream in streams_data["streams"]:
        sel_icon = "X" if stream["selected"] else ""
        type_display = f"{stream['type']} [red]*CENC[/red]" if stream["encrypted"] else stream["type"]
        
        variant_display = stream.get("variant", "")
        
        table.add_row(
            type_display, 
            sel_icon, 
            stream["resolution"] or "-",
            stream["bitrate"] or "-", 
            stream["codec"] or "-",
            stream["lang_code"] or "-", 
            stream.get("language_long", "-"),
            variant_display,
            "-", 
            str(stream["segments_count"]) if stream["segments_count"] else "-"
        )
    
    if external_subtitles:
        for ext_sub in external_subtitles:
            table.add_row(
                "Subtitle [yellow](Ext)[/yellow]", 
                "X", 
                "-", "-", "-",
                ext_sub.get("language", "unknown"),
                f"Ext ({ext_sub.get('language', 'unknown')})", 
                "",
                "-", "-"
            )
    
    console.print(table)