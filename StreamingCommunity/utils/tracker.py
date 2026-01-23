# 23-01-26 By GitHub Copilot

import time
import threading
from typing import Dict, Any, List


class DownloadTracker:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DownloadTracker, cls).__new__(cls)
                cls._instance._init_tracker()
            return cls._instance
            
    def _init_tracker(self):
        self.downloads: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        
    def start_download(self, download_id: str, title: str, site: str, media_type: str = "Film"):
        with self._lock:
            self.downloads[download_id] = {
                "id": download_id,
                "title": title,
                "site": site,
                "type": media_type,
                "status": "starting",
                "progress": 0,
                "speed": "0B/s",
                "size": "0B/0B",
                "segments": "0/0",
                "start_time": time.time(),
                "last_update": time.time(),
                "tasks": {} # For multi-stream downloads (video, audio, etc)
            }
            
    def update_progress(self, download_id: str, task_key: str, progress: float = None, speed: str = None, size: str = None, segments: str = None):
        with self._lock:
            if download_id in self.downloads:
                dl = self.downloads[download_id]
                dl["status"] = "downloading"
                dl["last_update"] = time.time()
                
                # Get or create task state
                if task_key not in dl["tasks"]:
                    dl["tasks"][task_key] = {
                        "progress": 0.0,
                        "speed": "0B/s",
                        "size": "0B/0B",
                        "segments": "0/0"
                    }
                
                task = dl["tasks"][task_key]
                
                # Update task fields if new values are provided
                if progress is not None:
                    try:
                        task["progress"] = float(progress)
                    except (ValueError, TypeError):
                        pass

                if speed: 
                    task["speed"] = speed
                if size: 
                    task["size"] = size
                if segments: 
                    task["segments"] = segments
                
                # Update main download state based on all active tasks
                video_audio_tasks = [t for k, t in dl["tasks"].items() if "video" in k.lower() or "audio" in k.lower() or "vid" in k.lower() or "aud" in k.lower()]
                
                if video_audio_tasks:
                    dl["progress"] = sum(t["progress"] for t in video_audio_tasks) / len(video_audio_tasks)
                    v_task = next((t for k, t in dl["tasks"].items() if "video" in k.lower() or "vid" in k.lower()), video_audio_tasks[0])
                    dl["speed"] = v_task["speed"]
                    dl["size"] = v_task["size"]
                    dl["segments"] = v_task["segments"]
                else:
                    dl["progress"] = task["progress"]
                    dl["speed"] = task["speed"]
                    dl["size"] = task["size"]
                    dl["segments"] = task["segments"]

    def complete_download(self, download_id: str, success: bool = True, error: str = None):
        with self._lock:
            if download_id in self.downloads:
                dl = self.downloads.pop(download_id)
                dl["status"] = "completed" if success else "failed"
                dl["end_time"] = time.time()
                dl["error"] = error
                dl["progress"] = 100 if success else dl["progress"]
                self.history.append(dl)

                # Limit history size
                if len(self.history) > 50:
                    self.history.pop(0)

    def get_active_downloads(self) -> List[Dict[str, Any]]:
        with self._lock:

            # Clean up old downloads that haven't been updated for a while (e.g. 5 minutes)
            now = time.time()
            to_remove = []
            for did, dl in self.downloads.items():
                if now - dl["last_update"] > 300: # 5 minutes timeout
                    to_remove.append(did)
            
            for did in to_remove:
                dl = self.downloads.pop(did)
                dl["status"] = "timed_out"
                self.history.append(dl)
                
            return list(self.downloads.values())

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self.history))


class ContextTracker:
    def __init__(self):
        self.local = threading.local()
    
    @property
    def download_id(self):
        return getattr(self.local, 'download_id', None)
    
    @download_id.setter
    def download_id(self, value):
        self.local.download_id = value

    @property
    def media_type(self):
        return getattr(self.local, 'media_type', 'Film')
    
    @media_type.setter
    def media_type(self, value):
        self.local.media_type = value

    @property
    def site_name(self):
        return getattr(self.local, 'site_name', None)
    
    @site_name.setter
    def site_name(self, value):
        self.local.site_name = value


# Global instance
download_tracker = DownloadTracker()
context_tracker = ContextTracker()