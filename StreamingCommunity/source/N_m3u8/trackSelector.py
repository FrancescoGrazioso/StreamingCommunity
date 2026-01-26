# 24.01.26

# External libraries
from rich.console import Console


# Logic
from .ui import build_table, run_selector


class TrackSelector:
    def __init__(self, streams):
        self.streams = streams

        # Initialize selection from streams that are marked selected by default
        self.selected = {i for i, s in enumerate(self.streams) if getattr(s, 'selected', False)}
        self.cursor = 0

        # Determine window size based on terminal height; cap to 12 rows to avoid lag
        try:
            term_height = Console().size.height or 24
        except Exception:
            term_height = 24
        
        # Leave room for headers and prompt; ensure at least 6 rows
        self.window_size = min(12, max(6, term_height - 6))
        self.console = Console()

        # Ensure at least one video is selected: if no video selected, pick first video
        try:
            video_indices = [i for i, s in enumerate(self.streams) if getattr(s, 'type', '').lower().startswith('video')]
            if video_indices and not any(i in self.selected for i in video_indices):
                self.selected.add(video_indices[0])
        except Exception:
            pass

    def preview(self) -> None:
        """Print static table without cursor highlight."""
        self.console.print(build_table(self.streams, self.selected, self.cursor, self.window_size, highlight_cursor=False))

    def _toggle_selection(self):
        s = self.streams[self.cursor]

        # Video: only one selected at a time
        if getattr(s, 'type', '').lower().startswith('video'):
            if self.cursor in self.selected:

                # Prevent deselecting the last remaining video
                current_video_selected = [i for i in self.selected if getattr(self.streams[i], 'type', '').lower().startswith('video')]
                if len(current_video_selected) <= 1 and current_video_selected[0] == self.cursor:
                    return
                
                self.selected.remove(self.cursor)
            else:
                # Remove any other video selections but keep audio/subs
                to_remove = {i for i in self.selected if getattr(self.streams[i], 'type', '').lower().startswith('video')}
                self.selected.difference_update(to_remove)
                self.selected.add(self.cursor)
        else:
            # Multi-select for audio/subtitles
            if self.cursor in self.selected:
                self.selected.remove(self.cursor)
            else:
                self.selected.add(self.cursor)

    def run(self):
        """Run interactive selection and return selected streams or None if canceled."""
        if not self.streams:
            return []

        def _toggle_with_state(state: dict):
            self.cursor = state.get('cursor', self.cursor)
            self._toggle_selection()
            state['selected'] = self.selected

        result = run_selector(self.streams, self.selected, self.cursor, self.window_size, _toggle_with_state)
        if result is None:
            return None
        return [self.streams[i] for i in result]