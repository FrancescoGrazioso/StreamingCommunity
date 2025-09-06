# 25.07.25

import os
import shutil


# External libraries
from rich.console import Console
from rich.panel import Panel


# Internal utilities
from StreamingCommunity.Util.config_json import config_manager
from StreamingCommunity.Util.os import internet_manager
from ...FFmpeg import print_duration_table


# Logic class
from .parser import MPDParser
from .segments import MPD_Segments
from .decrypt import decrypt_with_mp4decrypt
from .cdm_helpher import get_widevine_keys



# Config
DOWNLOAD_SPECIFIC_AUDIO = config_manager.get_list('M3U8_DOWNLOAD', 'specific_list_audio')
FILTER_CUSTOM_REOLUTION = str(config_manager.get('M3U8_CONVERSION', 'force_resolution')).strip().lower()
CLEANUP_TMP = config_manager.get_bool('M3U8_DOWNLOAD', 'cleanup_tmp_folder')


# Variable
console = Console()


class DASH_Downloader:
    def __init__(self, cdm_device, license_url, mpd_url, output_path):
        self.cdm_device = cdm_device
        self.license_url = license_url
        self.mpd_url = mpd_url
        self.out_path = os.path.splitext(os.path.abspath(str(output_path)))[0]
        self.original_output_path = output_path
        self.parser = None
        self._setup_temp_dirs()

        self.error = None
        self.stopped = False
        self.output_file = None

    def _setup_temp_dirs(self):
        """
        Create temporary folder structure under out_path\tmp
        """
        self.tmp_dir = os.path.join(self.out_path, "tmp")
        self.encrypted_dir = os.path.join(self.tmp_dir, "encrypted")
        self.decrypted_dir = os.path.join(self.tmp_dir, "decrypted")
        self.optimize_dir = os.path.join(self.tmp_dir, "optimize")
        
        os.makedirs(self.encrypted_dir, exist_ok=True)
        os.makedirs(self.decrypted_dir, exist_ok=True)
        os.makedirs(self.optimize_dir, exist_ok=True)

    def parse_manifest(self, custom_headers):
        self.parser = MPDParser(self.mpd_url)
        self.parser.parse(custom_headers)

        # Video info
        selected_video, list_available_resolution, filter_custom_resolution, downloadable_video = self.parser.select_video(FILTER_CUSTOM_REOLUTION)
        console.print(
            f"[cyan bold]Video    [/cyan bold] [green]Available:[/green] [purple]{', '.join(list_available_resolution)}[/purple] | "
            f"[red]Set:[/red] [purple]{filter_custom_resolution}[/purple] | "
            f"[yellow]Downloadable:[/yellow] [purple]{downloadable_video}[/purple]"
        )
        self.selected_video = selected_video

        # Audio info 
        selected_audio, list_available_audio_langs, filter_custom_audio, downloadable_audio = self.parser.select_audio(DOWNLOAD_SPECIFIC_AUDIO)
        console.print(
            f"[cyan bold]Audio    [/cyan bold] [green]Available:[/green] [purple]{', '.join(list_available_audio_langs)}[/purple] | "
            f"[red]Set:[/red] [purple]{filter_custom_audio}[/purple] | "
            f"[yellow]Downloadable:[/yellow] [purple]{downloadable_audio}[/purple]"
        )
        self.selected_audio = selected_audio

    def get_representation_by_type(self, typ):
        if typ == "video":
            return getattr(self, "selected_video", None)
        elif typ == "audio":
            return getattr(self, "selected_audio", None)
        return None

    def download_and_decrypt(self, custom_headers=None, custom_payload=None):
        """
        Download and decrypt video/audio streams. Sets self.error, self.stopped, self.output_file.
        Returns True if successful, False otherwise.
        """
        self.error = None
        self.stopped = False

        # Fetch keys immediately after obtaining PSSH
        if not self.parser.pssh:
            console.print("[red]No PSSH found: segments are not encrypted, skipping decryption.")
            self.download_segments(clear=True)
            return True

        keys = get_widevine_keys(
            pssh=self.parser.pssh,
            license_url=self.license_url,
            cdm_device_path=self.cdm_device,
            headers=custom_headers,
            payload=custom_payload
        )

        if not keys:
            console.print("[red]No keys found, cannot proceed with download.[/red]")
            return False

        # Extract the first key for decryption
        key = keys[0]
        KID = key['kid']
        KEY = key['key']

        for typ in ["video", "audio"]:
            rep = self.get_representation_by_type(typ)
            if rep:
                encrypted_path = os.path.join(self.encrypted_dir, f"{rep['id']}_encrypted.m4s")

                # If m4s file doesn't exist, start downloading
                if not os.path.exists(encrypted_path):
                    downloader = MPD_Segments(
                        tmp_folder=self.encrypted_dir,
                        representation=rep,
                        pssh=self.parser.pssh
                    )

                    try:
                        result = downloader.download_streams()

                        # Check for interruption or failure
                        if result.get("stopped"):
                            self.stopped = True
                            self.error = "Download interrupted"
                            return False
                        
                        if result.get("nFailed", 0) > 0:
                            self.error = f"Failed segments: {result['nFailed']}"
                            return False
                        
                    except Exception as ex:
                        self.error = str(ex)
                        return False

                decrypted_path = os.path.join(self.decrypted_dir, f"{typ}.mp4")
                result_path = decrypt_with_mp4decrypt(
                    encrypted_path, KID, KEY, output_path=decrypted_path
                )

                if not result_path:
                    self.error = f"Decryption of {typ} failed"
                    print(self.error)
                    return False

            else:
                self.error = f"No {typ} found"
                print(self.error)
                return False

        return True

    def download_segments(self, clear=False):
        # Download segments and concatenate them
        # clear=True: no decryption needed
        pass

    def finalize_output(self):

        # Use the original output path for the final file
        output_file = self.original_output_path
        
        # Set the output file path for status tracking
        self.output_file = output_file
        use_shortest = False

        """if os.path.exists(video_file) and os.path.exists(audio_file):
            audio_tracks = [{"path": audio_file}]
            out_audio_path, use_shortest = join_audios(video_file, audio_tracks, output_file)

        elif os.path.exists(video_file):
            out_video_path = join_video(video_file, output_file, codec=None)
        
        else:
            print("Video file missing, cannot export")
            return None
        """

        # Handle failed sync case
        if use_shortest:
            new_filename = output_file.replace(".mp4", "_failed_sync.mp4")
            os.rename(output_file, new_filename)
            output_file = new_filename
            self.output_file = new_filename

        # Display file information
        if os.path.exists(output_file):
            file_size = internet_manager.format_file_size(os.path.getsize(output_file))
            duration = print_duration_table(output_file, description=False, return_string=True)
            panel_content = (
                f"[cyan]File size: [bold red]{file_size}[/bold red]\n"
                f"[cyan]Duration: [bold]{duration}[/bold]\n"
                f"[cyan]Output: [bold]{os.path.abspath(output_file)}[/bold]"
            )
            
            console.print(Panel(
                panel_content,
                title=f"{os.path.basename(output_file.replace('.mp4', ''))}",
                border_style="green"
            ))

        # Clean up: delete only the tmp directory, not the main directory
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

        # Only remove the temp base directory if it was created specifically for this download
        # and if the final output is NOT inside this directory
        output_dir = os.path.dirname(self.original_output_path)
        
        # Check if out_path is different from the actual output directory
        # and if it's empty, then it's safe to remove
        if (self.out_path != output_dir and 
            os.path.exists(self.out_path) and 
            not os.listdir(self.out_path)):
            try:
                os.rmdir(self.out_path)
            except Exception as e:
                print(f"[WARN] Cannot remove directory {self.out_path}: {e}")

        # Verify the final file exists before returning
        if os.path.exists(output_file):
            return output_file
        else:
            self.error = "Final output file was not created successfully"
            return None
    
    def get_status(self):
        """
        Returns a dict with 'path', 'error', and 'stopped' for external use.
        """
        return {
            "path": self.output_file,
            "error": self.error,
            "stopped": self.stopped
        }
