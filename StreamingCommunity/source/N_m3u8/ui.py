# 24.01.26

# External libraries
from rich.table import Table
from rich.console import Console
from rich.live import Live
from rich import box


# Internal utilities
from StreamingCommunity.utils import internet_manager, get_key


# Logic
from ..utils.object import StreamInfo
from ..utils.trans_codec import get_audio_codec_name, get_video_codec_name, get_codec_type


def build_table(streams, selected: set, cursor: int, window_size: int = 12, highlight_cursor: bool = True):
    """Build and return the current table view"""

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="cyan",
        border_style="blue",
        padding=(0, 1)
    )

    cols = [
        ("#", "cyan"), 
        ("Type", "cyan"), 
        ("Ext", "magenta"), 
        ("Method", "red"), 
        ("Sel", "green"),
        ("Resolution", "yellow"), 
        ("Bitrate", "yellow"), 
        ("Codec", "green"),
        ("Language", "blue"), 
        ("Name", "green"), 
        ("Duration", "magenta"),
        ("Segments", "white")
    ]
    for col, color in cols:
        table.add_column(col, style=color, justify="right" if col in ("#", "Segments") else "left")

    total = len(streams)
    half = max(1, window_size // 2)
    start = max(0, cursor - half)
    end = min(total, start + window_size)
    if end - start < window_size:
        start = max(0, end - window_size)

    if start > 0:
        table.add_row("...", "", "", "", "", "", "", "", "", "", "", "")

    for visible_idx in range(start, end):
        s: StreamInfo = streams[visible_idx]

        idx = visible_idx
        is_selected = idx in selected
        is_cursor = (idx == cursor) and highlight_cursor
        bitrate = s.bandwidth
        if bitrate in ("0 bps", "N/A"):
            bitrate = ''
        if is_cursor:
            style = "bold white on blue"
        else:
            style = "dim" if idx % 2 == 1 else None
        
        # Transcode codec names
        readable_codecs = ""
        if "," in s.codec:
            for raw_codec in s.codec.split(","):
                if get_codec_type(raw_codec) == "Audio":
                    readable_codecs += f", {get_audio_codec_name(raw_codec)}"
                elif get_codec_type(raw_codec) == "Video":
                    readable_codecs += get_video_codec_name(raw_codec)
        else:
            if get_codec_type(s.codec) == "Audio":
                readable_codecs = get_audio_codec_name(s.codec)
            elif get_codec_type(s.codec) == "Video":
                readable_codecs = get_video_codec_name(s.codec)

        table.add_row(
            str(idx + 1),
            f"{s.type}",
            s.extension or '',
            str(s.segments_protection),
            "X" if is_selected else "",
            s.resolution if s.type == "Video" else "",
            bitrate,
            readable_codecs,
            s.language or '',
            s.name or '',
            internet_manager.format_time(s.total_duration, add_hours=True) if s.total_duration > 0 else "N/A",
            str(s.segment_count),
            style=style
        )

    if end < total:
        table.add_row("...", "", "", "", "", "", "", "", "", "", "", "")
    return table


def run_selector(streams, selected: set, cursor: int, window_size: int, toggle_callback):
    """Run interactive live selector."""
    console = Console()
    state = {'cursor': cursor, 'selected': selected}

    refresh_rate = 2
    with Live(build_table(streams, state['selected'], state['cursor'], window_size), refresh_per_second=refresh_rate, auto_refresh=False, vertical_overflow="crop", console=console, transient=True) as live:
        last_cursor = state['cursor']
        last_selected = set(state['selected'])

        while True:
            key = get_key()
            
            if key is None:
                continue

            if key == 'UP':
                state['cursor'] = (state['cursor'] - 1) % len(streams)
            elif key == 'DOWN':
                state['cursor'] = (state['cursor'] + 1) % len(streams)
            elif key == 'SPACE' or key == 'RIGHT':
                try:
                    toggle_callback(state)
                except Exception:
                    pass
            elif key == 'LEFT':
                if state['cursor'] in state['selected']:
                    state['selected'].remove(state['cursor'])
            elif key == 'ENTER':
                return sorted(list(state['selected']))
            elif key == 'ESC':
                return None

            if state['cursor'] != last_cursor or state['selected'] != last_selected:
                live.update(build_table(streams, state['selected'], state['cursor'], window_size), refresh=True)
                last_cursor = state['cursor']
                last_selected = set(state['selected'])