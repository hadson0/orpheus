import os
import re
from typing import Optional, Dict, Any, Tuple
import spotipy
from flask import current_app
from app.services.auth_service import get_valid_token

COMMAND_KEYWORDS_REGEX = {
    "play_album": r"^(?:play|tocar|ouvir|escutar)\s+(?:album|álbum)\s+(.+)",
    "play_artist": r"^(?:play|tocar|ouvir|escutar)\s+artist(?:a)?\s+(.+)",
    "play_track": r"^(?:play|tocar|ouvir|escutar)\s+m[uú]sica\s+(.+)",
    "play_playlist": r"^(?:play|tocar|ouvir|escutar)\s+playlist\s+(.+)",
    "add_to_queue": r"^(?:add\s+to\s+queue|queue\s+song|adicionar\s+na\s+fila|colocar\s+na\s+fila)\s+(.+)",
    "play": r"^(?:play|resume|continue|retomar|continuar|tocar)$",
    "pause": r"^(?:pause|stop|hold|pausar|parar|segurar)$",
    "next": r"^(?:next|skip|forward|pr[oó]xima|pular|avan[cç]ar)$",
    "previous": r"^(?:previous|back|rewind|last|anterior|voltar|retroceder|[uú]ltima)$",
}


def get_spotify_client(device_id: str):
    """
    Returns an authenticated Spotipy client for the device_id.
    """
    token = get_valid_token(device_id)
    if not token:
        raise Exception("Device not authenticated or token expired")
    return spotipy.Spotify(auth=token)


def parse_command(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Parses the transcribed text to find a command and extract a name if applicable.
    Returns a tuple of (command, name) or None if no command is found.
    """
    if not text:
        return None

    normalized_text = text.lower().strip()
    filler_words = [
        "please",
        "can you",
        "could you",
        "would you",
        "spotify",
        "por favor",
        "você pode",
        "voce pode",
        "poderia",
        "seria possível",
        "seria possivel",
    ]
    for filler in filler_words:
        normalized_text = normalized_text.replace(filler, "").strip()

    # Process commands using the regex dictionary
    for command, pattern in COMMAND_KEYWORDS_REGEX.items():
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match:
            # If the regex has capturing groups, the first group is the name.
            # Otherwise, it's a simple command with no associated name.
            name = match.group(1).strip().rstrip(".!?,;") if match.groups() else None
            return command, name

    return None


def execute_command(
    command: str, name: Optional[str], device_id: str
) -> Dict[str, Any]:
    """
    Executes the given command. The 'name' parameter is now passed directly from parse_command.
    """
    try:
        sp = get_spotify_client(device_id)
        if command == "play":
            sp.start_playback()
            return {"success": True, "command": command, "message": "Playback resumed"}
        elif command == "pause":
            sp.pause_playback()
            return {"success": True, "command": command, "message": "Playback paused"}
        elif command == "next":
            sp.next_track()
            return {
                "success": True,
                "command": command,
                "message": "Skipped to next track",
            }
        elif command == "previous":
            sp.previous_track()
            return {
                "success": True,
                "command": command,
                "message": "Went to previous track",
            }

        elif command in ["play_track", "add_to_queue"]:
            if not name:
                return {
                    "success": False,
                    "command": command,
                    "message": "No track name found",
                }

            # Try to separate track name and artist for a more precise search
            track_name = name
            artist_name = None
            by_separators = [" by ", " por ", " de "]
            for sep in by_separators:
                if sep in name.lower():
                    parts = re.split(
                        re.escape(sep), name, maxsplit=1, flags=re.IGNORECASE
                    )
                    track_name = parts[0].strip()
                    artist_name = parts[1].strip()
                    break

            if artist_name:
                query = f'track:"{track_name}" artist:"{artist_name}"'
            else:
                query = f'track:"{track_name}"'

            results = sp.search(q=query, limit=1, type="track")
            if not results["tracks"]["items"]:
                results = sp.search(q=name, limit=1, type="track")
                if not results["tracks"]["items"]:
                    return {
                        "success": False,
                        "command": command,
                        "message": f"Track '{name}' not found",
                    }

            track = results["tracks"]["items"][0]
            uri = track["uri"]
            track_name_found = track["name"]

            if command == "play_track":
                sp.start_playback(uris=[uri])
                return {
                    "success": True,
                    "command": command,
                    "message": f"Playing track: {track_name_found}",
                }
            else:
                sp.add_to_queue(uri=uri)
                return {
                    "success": True,
                    "command": command,
                    "message": f"Added '{track_name_found}' to the queue",
                }

        elif command == "play_artist":
            if not name:
                return {
                    "success": False,
                    "command": command,
                    "message": "No artist name found",
                }

            query = f'artist:"{name}"'
            results = sp.search(q=query, limit=1, type="artist")
            if not results["artists"]["items"]:
                results = sp.search(q=name, limit=1, type="artist")
                if not results["artists"]["items"]:
                    return {
                        "success": False,
                        "command": command,
                        "message": f"Artist '{name}' not found",
                    }

            artist = results["artists"]["items"][0]
            artist_uri = artist["uri"]
            artist_name_found = artist["name"]
            sp.start_playback(context_uri=artist_uri)
            return {
                "success": True,
                "command": command,
                "message": f"Playing artist: {artist_name_found}",
            }

        elif command == "play_album":
            if not name:
                return {
                    "success": False,
                    "command": command,
                    "message": "No album name found",
                }

            query = f'album:"{name}"'
            results = sp.search(q=query, limit=1, type="album")
            if not results["albums"]["items"]:
                results = sp.search(q=name, limit=1, type="album")
                if not results["albums"]["items"]:
                    return {
                        "success": False,
                        "command": command,
                        "message": f"Album '{name}' not found",
                    }

            album = results["albums"]["items"][0]
            album_uri = album["uri"]
            album_name_found = album["name"]
            sp.start_playback(context_uri=album_uri)
            return {
                "success": True,
                "command": command,
                "message": f"Playing album: {album_name_found}",
            }

        elif command == "play_playlist":
            if not name:
                return {
                    "success": False,
                    "command": command,
                    "message": "No playlist name found",
                }

            query = f'playlist:"{name}"'
            results = sp.search(q=query, limit=1, type="playlist")
            if not results["playlists"]["items"]:
                results = sp.search(q=name, limit=1, type="playlist")
                if not results["playlists"]["items"]:
                    return {
                        "success": False,
                        "command": command,
                        "message": f"Playlist '{name}' not found",
                    }

            playlist = results["playlists"]["items"][0]
            playlist_uri = playlist["uri"]
            playlist_name_found = playlist["name"]
            sp.start_playback(context_uri=playlist_uri)
            return {
                "success": True,
                "command": command,
                "message": f"Playing playlist: {playlist_name_found}",
            }

        else:
            return {"success": False, "command": command, "message": "Unknown command"}
    except Exception as e:
        return {
            "success": False,
            "command": command,
            "message": f"Error executing '{command}': {str(e)}",
        }


def get_playback_state(device_id: str) -> Optional[Dict[str, Any]]:
    try:
        sp = get_spotify_client(device_id)
        playback = sp.current_playback()
        return playback
    except Exception:
        return None


def test_spotify_connection(device_id: str) -> bool:
    try:
        get_playback_state(device_id)
        return True
    except Exception:
        return False
