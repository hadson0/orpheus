# Orpheus - Spotify Voice Bridge API

Orpheus is an API that bridges voice commands to Spotify playback, enabling you to control your Spotify devices through speech. It leverages OpenAI Whisper for transcription and the Spotify Web API for playback.

## Why "Orpheus"?
In Greek mythology, [**Orpheus**](https://en.wikipedia.org/wiki/Orpheus) was a legendary musician and poet whose music could charm anyone, even inanimate objects. This project is named Orpheus because it empowers your voice to control your Spotify devices, just as Orpheus did with his music.

---

## Features

- **Voice Command to Spotify**: Execute voice commands on the last active Spotify device.
- **OAuth2 Device Authentication**: Per-device Spotify login via QR code.
- **Playback Control**: Play, pause, skip, previous, play album/artist/playlist/track, and add to queue.
- **OpenAI Whisper Integration**: Speech-to-text transcription.
- **Secure Token Storage**: Encrypted storage of Spotify tokens per device.
- **RESTful API**
- **Small QR Codes for Authentication**: Supports low-resolution displays.

---

---

## Table of Contents

- [Orpheus - Spotify Voice Bridge API](#orpheus---spotify-voice-bridge-api)
  - [Why "Orpheus"?](#why-orpheus)
  - [Features](#features)
  - [Table of Contents](#table-of-contents)
  - [Quick Start](#quick-start)
    - [1. Clone the Repository](#1-clone-the-repository)
    - [2. Install Dependencies](#2-install-dependencies)
      - [Linux](#linux)
      - [Windows](#windows)
    - [3. Configure Environment](#3-configure-environment)
    - [4. Initialize the Database](#4-initialize-the-database)
    - [5. Run the Server](#5-run-the-server)
  - [API Overview](#api-overview)
    - [Device Authentication](#device-authentication)
    - [Voice Command](#voice-command)
    - [Token Management](#token-management)
    - [Utilities](#utilities)
  - [Example: Voice Command Flow](#example-voice-command-flow)
  - [Security](#security)
  - [Requirements](#requirements)
  - [License](#license)
  - [Contributing](#contributing)
  - [API Reference](#api-reference)
    - [Device Authentication](#device-authentication-1)
      - [`GET /qr/<device_id>`](#get-qrdevice_id)
      - [`GET /auth/callback`](#get-authcallback)
    - [Voice Command](#voice-command-1)
      - [`POST /command`](#post-command)
    - [Token Management](#token-management-1)
      - [`POST /refresh`](#post-refresh)
    - [Utilities](#utilities-1)
      - [`GET /health`](#get-health)
      - [`GET /device/<device_id>/status`](#get-devicedevice_idstatus)
      - [`GET /u/<code>`](#get-ucode)
    - [Interactive API Docs](#interactive-api-docs)

---
## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/hadson0/orpheus.git
cd orpheus
```

### 2. Install Dependencies

#### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

> **Windows:**  
> Use `copy .env.example .env` instead of `cp .env.example .env`.

Edit `.env` and set your Spotify API credentials, OpenAI API key, and encryption key.

### 4. Initialize the Database

```bash
flask db upgrade
```

### 5. Run the Server

```bash
python run.py
```

---

## API Overview

### Device Authentication

- `GET /qr/<device_id>`  
    Returns a QR code for device authentication via Spotify OAuth2.

- `GET /auth/callback`  
    Handles Spotify OAuth2 callback.

### Voice Command

- `POST /command`  
    Accepts a device ID and audio file, transcribes the command, and executes it on Spotify.

### Token Management

- `POST /refresh`  
    Manually refreshes a device's Spotify token.

### Utilities

- `GET /health`  
    Health check endpoint.

- `GET /device/<device_id>/status`  
    Returns authentication status for a device.

---

## Example: Voice Command Flow

1. Device requests `/qr/<device_id>` and displays the QR code.
2. User scans the QR code and authenticates with Spotify.
3. Device records audio and sends it to `/command` with its `device_id`.
4. The API transcribes the audio and executes the corresponding Spotify action.

---

## Security

- All tokens are encrypted at rest.
- OAuth2 state is validated and time-limited.
- Supports secure configuration for production (HTTPS, secure cookies, etc.).

---

## Requirements

- Python 3.8+
- Spotify Developer Account
- OpenAI API Key (for Whisper)
- [See `requirements.txt`](requirements.txt)

---

## License

This project is licensed under the [GNU GPL v3](LICENSE).

---

## Contributing

Pull requests and issues are welcome!

---

## API Reference

### Device Authentication

#### `GET /qr/<device_id>`
Returns a PNG QR code for device authentication via Spotify OAuth2.

**Path Parameters:**
- `device_id` (string, required): Device identifier.

**Responses:**
- `200`: PNG image with QR code.
- `400`: Invalid device ID.
- `500`: Internal server error.

---

#### `GET /auth/callback`
Handles Spotify OAuth2 callback.

**Query Parameters:**
- `code` (string, optional): Authorization code from Spotify.
- `state` (string, optional): State parameter for CSRF protection.
- `error` (string, optional): Error message from Spotify.

**Responses:**
- `200`: Success HTML page.
- `400`: Error HTML page.
- `500`: Internal server error.

---

### Voice Command

#### `POST /command`
Accepts a device ID and audio file, transcribes the command, and executes it on Spotify.

**Form Data:**
- `device_id` (string, required): Device identifier.
- `audio` (file, required): Audio file with voice command.

**Responses:**
- `200`: Command processed.
- `400`: Bad request.
- `401`: Unauthorized.
- `500`: Internal server error.

---

### Token Management

#### `POST /refresh`
Manually refreshes a device's Spotify token.

**JSON Body:**
- `device_id` (string, required): Device identifier.

**Responses:**
- `200`: Token refreshed.
- `400`: Bad request or refresh failed.
- `500`: Internal server error.

---

### Utilities

#### `GET /health`
Health check endpoint.

**Responses:**
- `200`: Service is healthy.

---

#### `GET /device/<device_id>/status`
Returns authentication status for a device.

**Path Parameters:**
- `device_id` (string, required): Device identifier.

**Responses:**
- `200`: Device status.
- `404`: Device not found.
- `500`: Internal server error.

---

#### `GET /u/<code>`
Redirects to the long URL from a short code.

**Path Parameters:**
- `code` (string, required): Short URL code.

**Responses:**
- `302`: Redirect to long URL.
- `404`: Code not found.

---

### Interactive API Docs

After running the server, access `/apidocs` for interactive Swagger documentation.