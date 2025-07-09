from __future__ import annotations

import re
from typing import Optional, Dict, Any, Callable

import spotipy
from flask import current_app

from app.services.auth_service import get_valid_token

FILLER_WORDS = {
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
}

COMMAND_PATTERNS: dict[str, str] = {
    "play_album": r"^(?:play|tocar?|ouvir|escutar?)\s+(?:album|álbum)\s+(.+)",
    "play_artist": r"^(?:play|tocar?|ouvir|escutar?)\s+artist(?:a)?\s+(.+)",
    "play_track": r"^(?:play|tocar?|ouvir|escutar?)\s+m[uú]sica\s+(.+)",
    "play_playlist": r"^(?:play|tocar?|ouvir|escutar?)\s+playlist\s+(.+)",
    "add_to_queue": r"^(?:add\s+to\s+queue|queue\s+song|adicionar\s+na\s+fila|"
    r"colocar\s+na\s+fila)\s+(.+)",
    "play": r"^(?:play|resume|continue|retomar|continuar|tocar)$",
    "pause": r"^(?:pause|stop|hold|pausar|parar|segurar)$",
    "next": r"^(?:next|skip|forward|pr[oó]xima|pular|avan[cç]ar)$",
    "previous": r"^(?:previous|back|rewind|last|anterior|voltar|retroceder|[uú]ltima)$",
}

_BY_SEPARATORS = (" by ", " por ", " de ")


def _spotify(device_id: str) -> spotipy.Spotify:
    token = get_valid_token(device_id)
    if not token:
        raise RuntimeError("Device not authenticated or token expired")
    return spotipy.Spotify(auth=token)


def _normalise(text: str) -> str:
    text = text.lower().strip()
    for filler in sorted(FILLER_WORDS, key=len, reverse=True):
        text = text.replace(filler, "").strip()
    return " ".join(text.split())


def _search_first(
    sp: spotipy.Spotify, query: str, item_type: str
) -> Optional[dict[str, Any]]:
    """Return first Spotify search result or None."""
    result = sp.search(q=query, limit=1, type=item_type)
    items_key = f"{item_type}s"
    items = result.get(items_key, {}).get("items", [])
    return items[0] if items else None


def _failure(cmd: str, msg: str, details: Optional[str] = None) -> Dict[str, Any]:
    payload = {"success": False, "command": cmd, "message": msg}
    if details:
        payload["details"] = details
    return payload


def _success(cmd: str, msg: str) -> Dict[str, Any]:
    return {"success": True, "command": cmd, "message": msg}


def parse_command(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Parse free text and return (command, argument|None), or None if unknown."""
    if not text:
        return None

    text = _normalise(text)
    for cmd, pattern in COMMAND_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return cmd, (m.group(1).strip(" .!?,;") if m.groups() else None)
    return None


def _split_track_artist(name: str) -> tuple[str, Optional[str]]:
    """Split 'track [by] artist' patterns if possible."""
    for sep in _BY_SEPARATORS:
        if sep in name.lower():
            track, artist = re.split(
                re.escape(sep), name, maxsplit=1, flags=re.IGNORECASE
            )
            return track.strip(), artist.strip()
    return name, None


def execute_command(
    command: str, name: Optional[str], device_id: str
) -> Dict[str, Any]:
    """
    Executes the given command using the correct, sequential logic.
    """
    try:
        sp = _spotify(device_id)

        # --- LÓGICA CORRIGIDA USANDO IF/ELIF (COMO NO SEU CÓDIGO ANTIGO) ---

        if command == "play":
            sp.start_playback()
            return _success(command, "Playback resumed")

        elif command == "pause":
            sp.pause_playback()
            return _success(command, "Playback paused")

        elif command == "next":
            sp.next_track()
            return _success(command, "Skipped to next track")

        elif command == "previous":
            sp.previous_track()
            return _success(command, "Went to previous track")

        elif command in ["play_track", "add_to_queue"]:
            if not name:
                return _failure(command, "No track name found")

            track_q, artist_q = _split_track_artist(name)
            query = f'track:"{track_q}"' + (f' artist:"{artist_q}"' if artist_q else "")
            track = _search_first(sp, query, "track") or _search_first(sp, name, "track")

            if not track:
                return _failure(command, f"Track '{name}' not found")

            if command == "add_to_queue":
                sp.add_to_queue(track["uri"])
                return _success("add_to_queue", f"Added '{track['name']}' to the queue")
            else: # play_track
                sp.start_playback(uris=[track["uri"]])
                return _success("play_track", f"Playing track: {track['name']}")

        elif command == "play_artist":
            if not name:
                return _failure(command, "No artist name found")
            artist = _search_first(sp, f'artist:"{name}"', "artist") or _search_first(sp, name, "artist")
            if not artist:
                return _failure(command, f"Artist '{name}' not found")
            sp.start_playback(context_uri=artist["uri"])
            return _success(command, f"Playing artist: {artist['name']}")

        elif command == "play_album":
            if not name:
                return _failure(command, "No album name found")
            album = _search_first(sp, f'album:"{name}"', "album") or _search_first(sp, name, "album")
            if not album:
                return _failure(command, f"Album '{name}' not found")
            sp.start_playback(context_uri=album["uri"])
            return _success(command, f"Playing album: {album['name']}")

        elif command == "play_playlist":
            if not name:
                return _failure(command, "No playlist name found")
            playlist = _search_first(sp, f'playlist:"{name}"', "playlist") or _search_first(sp, name, "playlist")
            if not playlist:
                return _failure(command, f"Playlist '{name}' not found")
            sp.start_playback(context_uri=playlist["uri"])
            return _success(command, f"Playing playlist: {playlist['name']}")

        else:
            return _failure(command, "Unknown command")

    except Exception as exc:
        current_app.logger.exception("Error executing command %s", command)
        return _failure(command, f"Error executing '{command}'", str(exc))


def get_playback_state(device_id: str) -> Optional[Dict[str, Any]]:
    try:
        return _spotify(device_id).current_playback()
    except Exception:
        return None


def test_spotify_connection(device_id: str) -> bool:
    return get_playback_state(device_id) is not None