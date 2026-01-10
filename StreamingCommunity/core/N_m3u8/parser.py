# 10.01.26

import re
import os
import json
from typing import Optional, Tuple


# Logic class
from .models import StreamInfo, Stream, DownloadProgress


class StreamParser:
    PROGRESS = re.compile(
        r"(Vid|Aud|Sub)\s+"
        r"([^\u2500\-]+?)\s+"
        r"[\u2500\-\s]*"
        r"(\d+)/(\d+)\s+"
        r"([\d.]+)%"
        r"(?:\s*([\d.]+[KMGT]*B?)/?([\d.]+[KMGT]*B?))?"
        r"(?:\s*([\d.]+[KMGT]*Bps))?"
        r"(?:\s*([\d:.\-]+))?"
    )
    
    @staticmethod
    def _extract_variant_from_language(language_code: str) -> Tuple[str, str]:
        """Extract base language and variant from language code."""
        if language_code.startswith("forced-"):
            return language_code.replace("forced-", ""), "Forced"
        elif language_code.startswith("sdh-"):
            return language_code.replace("sdh-", ""), "SDH"
        elif language_code.endswith("-forced"):
            return language_code.replace("-forced", ""), "Forced"
        elif language_code.endswith("-sdh"):
            return language_code.replace("-sdh", ""), "SDH"
        return language_code, ""
    
    @staticmethod
    def _extract_variant_from_name(name: str) -> Tuple[str, str]:
        """Extract clean name and variant from name field."""
        # Check for square brackets variants [CC], [Forced], [SDH], etc.
        match_square = re.match(r'^(.+?)\s*\[(.+?)\]\s*$', name)
        if match_square:
            base_name = match_square.group(1).strip()
            variant = match_square.group(2).strip()
            return base_name, variant
        
        # Check for parenthesized variants (Simplified, Traditional, etc.)
        match_paren = re.match(r'^(.+?)\s*\((.+?)\)\s*$', name)
        if match_paren:
            base_name = match_paren.group(1).strip()
            variant = match_paren.group(2).strip()
            return base_name, variant
        
        return name, ""
    
    @staticmethod
    def parse_stream_info_from_json(meta_file_path, manifest_type_hint: str = None) -> StreamInfo:
        """Parse stream info directly from meta.json file"""
        if not os.path.exists(meta_file_path):
            return StreamInfo("UNKNOWN", [])
        
        try:
            with open(meta_file_path, 'r', encoding='utf-8-sig') as f:
                meta_data = json.load(f)
        except Exception as e:
            print(f"Error reading meta.json: {e}")
            return StreamInfo("UNKNOWN", [])
        
        streams = []
        manifest_type = manifest_type_hint if manifest_type_hint else "UNKNOWN"
        
        # Process each item in the meta.json array
        for item in meta_data:
            media_type = item.get("MediaType", "VIDEO").upper()
            
            if not manifest_type_hint and manifest_type == "UNKNOWN":
                if "Codecs" in item and "Resolution" in item:
                    manifest_type = "DASH"
            
            # VIDEO streams
            if media_type == "VIDEO" or (media_type not in ["AUDIO", "SUBTITLES"] and "Resolution" in item):
                resolution = item.get("Resolution", "Unknown")
                bandwidth = item.get("Bandwidth", 0)
                codecs = item.get("Codecs", "unknown")
                segments_count = item.get("SegmentsCount", 0)
                bitrate = f"{bandwidth // 1000} Kbps" if bandwidth else "-"

                is_encrypted = False
                if "Playlist" in item and "MediaInit" in item["Playlist"]:
                    encrypt_info = item["Playlist"]["MediaInit"].get("EncryptInfo", {})
                    is_encrypted = encrypt_info.get("Method") is not None
                
                duration = "-"
                if "Playlist" in item and "TotalDuration" in item["Playlist"]:
                    total_duration = item["Playlist"]["TotalDuration"]
                    minutes = int(total_duration // 60)
                    seconds = int(total_duration % 60)
                    duration = f"~{minutes}m{seconds}s"
                
                stream = Stream(
                    type="Video",
                    resolution=resolution,
                    bitrate=bitrate,
                    codec=codecs,
                    language="-",
                    lang_code="-",
                    language_long="-",
                    variant="",
                    encrypted=is_encrypted,
                    duration=duration,
                    segments_count=segments_count
                )
                streams.append(stream)
            
            # AUDIO streams
            elif media_type == "AUDIO":
                language = item.get("Language", "unknown")
                name = item.get("Name", language)
                bandwidth = item.get("Bandwidth", 0)
                codecs = item.get("Codecs", "unknown")
                segments_count = item.get("SegmentsCount", 0)
                base_language, variant_from_code = StreamParser._extract_variant_from_language(language)
                clean_name, variant_from_name = StreamParser._extract_variant_from_name(name)
                final_variant = variant_from_code if variant_from_code else variant_from_name
                bitrate = f"{bandwidth // 1000} Kbps" if bandwidth else "-"
                
                is_encrypted = False
                if "Playlist" in item and "MediaInit" in item["Playlist"]:
                    encrypt_info = item["Playlist"]["MediaInit"].get("EncryptInfo", {})
                    is_encrypted = encrypt_info.get("Method") is not None
                
                duration = "-"
                if "Playlist" in item and "TotalDuration" in item["Playlist"]:
                    total_duration = item["Playlist"]["TotalDuration"]
                    minutes = int(total_duration // 60)
                    seconds = int(total_duration % 60)
                    duration = f"~{minutes}m{seconds}s"
                
                stream = Stream(
                    type="Audio",
                    resolution="-",
                    bitrate=bitrate,
                    codec=codecs,
                    language=base_language,
                    lang_code=base_language,
                    language_long=clean_name,
                    variant=final_variant,
                    encrypted=is_encrypted,
                    duration=duration,
                    segments_count=segments_count
                )
                streams.append(stream)
            
            # SUBTITLE streams
            elif media_type == "SUBTITLES":
                language = item.get("Language", "unknown")
                name = item.get("Name", language)
                segments_count = item.get("SegmentsCount", 0)
                base_language, variant_from_code = StreamParser._extract_variant_from_language(language)
                clean_name, variant_from_name = StreamParser._extract_variant_from_name(name)
                final_variant = variant_from_code if variant_from_code else variant_from_name
                
                is_encrypted = False
                if "Playlist" in item and "MediaInit" in item["Playlist"]:
                    encrypt_info = item["Playlist"]["MediaInit"].get("EncryptInfo", {})
                    is_encrypted = encrypt_info.get("Method") is not None
                
                duration = "-"
                if "Playlist" in item and "TotalDuration" in item["Playlist"]:
                    total_duration = item["Playlist"]["TotalDuration"]
                    minutes = int(total_duration // 60)
                    seconds = int(total_duration % 60)
                    duration = f"~{minutes}m{seconds}s"
                
                stream = Stream(
                    type="Subtitle",
                    resolution="-",
                    bitrate="-",
                    codec="-",
                    language=base_language,
                    lang_code=base_language,
                    language_long=clean_name,
                    variant=final_variant,
                    encrypted=is_encrypted,
                    duration=duration,
                    segments_count=segments_count
                )
                streams.append(stream)
        
        streams = StreamParser._deduplicate_subtitles(streams)
        return StreamInfo(manifest_type, streams)
    
    @staticmethod
    def _deduplicate_subtitles(streams: list) -> list:
        """Remove duplicate subtitle streams"""
        seen_subtitles = {}
        result = []
        
        for stream in streams:
            if stream.type == "Subtitle":
                key = (
                    stream.language.lower(),
                    stream.lang_code.lower(),
                    stream.language_long.lower(),
                    stream.variant.lower()
                )
                
                if key not in seen_subtitles:
                    seen_subtitles[key] = True
                    result.append(stream)
            else:
                result.append(stream)
        
        return result
    
    @staticmethod
    def parse_progress(line: str) -> Optional[DownloadProgress]:
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        match = StreamParser.PROGRESS.search(clean_line)
        if not match:
            return None
        
        try:
            stream_type = match.group(1)
            description = match.group(2).strip()
            current = int(match.group(3))
            total = int(match.group(4))
            percent = float(match.group(5))
            downloaded_size = match.group(6) or "-"
            total_size = match.group(7) or "-"
            speed = match.group(8) or "-"
            time_remaining = match.group(9) or "--:--:--"
            
            return DownloadProgress(
                stream_type=stream_type,
                description=description,
                current=current,
                total=total,
                percent=percent,
                downloaded_size=downloaded_size,
                total_size=total_size,
                speed=speed,
                time=time_remaining
            )
        except (ValueError, IndexError):
            return None