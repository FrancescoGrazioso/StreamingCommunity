# 21.04.25

import logging
import threading
from typing import Dict


# External libraries
from tqdm import tqdm


# Internal utilities
from StreamingCommunity.Util import internet_manager, Colors


class M3U8_Ts_Estimator:
    def __init__(self, total_segments: int, segments_instance=None):
        """
        Initialize the M3U8_Ts_Estimator object.
        
        Parameters:
            - total_segments (int): Length of total segments to download.
        """
        self.ts_file_sizes = []
        self.total_segments = total_segments
        self.segments_instance = segments_instance
        self.lock = threading.Lock()
        self.downloaded_segments_count = 0

    def add_ts_file(self, size: int):
        """Add a file size to the list of file sizes."""
        if size <= 0:
            return

        with self.lock:
            self.ts_file_sizes.append(size)

    def calculate_total_size(self) -> str:
        """
        Calculate the estimated total size of all segments.

        Returns:
            str: The estimated total size in a human-readable format.
        """
        try:
            with self.lock:
                if not self.ts_file_sizes:
                    return "0 B"
                    
                mean_segment_size = sum(self.ts_file_sizes) / len(self.ts_file_sizes)
                estimated_total_size = mean_segment_size * self.total_segments
                return internet_manager.format_file_size(estimated_total_size)

        except Exception as e:
            logging.error("An unexpected error occurred: %s", e)
            return "Error"
    
    def update_progress_bar(self, segment_size: int, progress_counter: tqdm) -> None:
        """
        Update progress bar with segment information.
        
        Parameters:
            - segment_size (int): Size in bytes of the current downloaded segment
            - progress_counter (tqdm): Progress bar instance to update
        """
        try:
            self.add_ts_file(segment_size)
            file_total_size = self.calculate_total_size()
            
            if file_total_size == "Error":
                return
                
            number_file_total_size, units_file_total_size = file_total_size.split(' ', 1)
        
            progress_str = (
                f"{Colors.LIGHT_GREEN}{number_file_total_size} {Colors.LIGHT_MAGENTA}{units_file_total_size}"
            )
            
            progress_counter.set_postfix_str(progress_str)
            
        except Exception as e:
            logging.error(f"Error updating progress bar: {str(e)}")
    
    def get_average_segment_size(self) -> int:
        """Returns average segment size in bytes."""
        with self.lock:
            if not self.ts_file_sizes:
                return 0
            return int(sum(self.ts_file_sizes) / len(self.ts_file_sizes))
    
    def get_stats(self, downloaded_count: int = None, total_segments: int = None) -> Dict:
        """Returns comprehensive statistics for API."""
        with self.lock:
            avg_size = self.get_average_segment_size()
            total_downloaded = sum(self.ts_file_sizes)
            
            return {
                'total_segments': self.total_segments,
                'downloaded_count': len(self.ts_file_sizes),
                'average_segment_size': avg_size,
                'total_downloaded_bytes': total_downloaded,
                'estimated_total_size': self.calculate_total_size()
            }