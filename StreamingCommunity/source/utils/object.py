# 04.01.25

class StreamInfo:
    def __init__(self, type_: str, language: str = "", resolution: str = "", codec: str = "", bandwidth: str = "", raw_bandwidth: str = "", name: str = "", selected: bool = False, 
            extension: str = "", total_duration: float = 0.0, segment_count: int = 0, segments_protection: str = "NONE"):
        self.type = type_
        self.resolution = resolution
        self.language = language
        self.name = name
        self.bandwidth = bandwidth
        self.raw_bandwidth = raw_bandwidth
        self.codec = codec
        self.selected = selected
        self.extension = extension
        self.total_duration = total_duration
        self.segment_count = segment_count
        self.final_size = None
        self.segments_protection = segments_protection