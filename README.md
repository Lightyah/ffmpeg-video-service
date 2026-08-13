# FFmpeg Video Assembly Service

A small self-hosted API that turns (image + audio + caption) into a Ken Burns-style
scene video, and concatenates multiple scene videos into a final video.
Built for zero-budget YouTube Shorts automation pipelines (n8n-friendly).

## Endpoints

### `GET /`
Health check.

### `POST /render-scene`
Body (JSON):
```json
{
  "image_url": "https://...",
  "audio_url": "https://...",
  "caption": "Barnaby waited every day at 5pm.",
  "width": 1080,
  "height": 1920
}
```
Returns: `scene.mp4` (binary)

### `POST /concatenate`
Body (JSON):
```json
{
  "video_urls": ["https://.../scene1.mp4", "https://.../scene2.mp4"]
}
```
Returns: `final.mp4` (binary)

## Auth
If the `API_KEY` environment variable is set, requests must include:
```
Authorization: Bearer YOUR_API_KEY
```
If `API_KEY` is not set, the service is open (no auth required).

## Deploying on Render (free tier)
1. Push this folder to a GitHub repo.
2. On Render: New + -> Web Service -> connect the repo.
3. Render auto-detects the Dockerfile.
4. Instance Type: Free.
5. (Optional) Add an Environment Variable: `API_KEY` = your own secret string.
6. Deploy. Note: free tier sleeps after 15 min idle; first request after sleep
   can take 30-60+ seconds to respond. Set generous timeouts (60s+) in n8n.

## Notes
- `render-scene` times the video to match the audio's exact duration.
- Ken Burns effect is a slow, steady zoom-in (adjust the `0.0007` zoom speed
  in `app.py` to make it faster/slower).
- Captions are burned in (hardcoded into the video), centered near the bottom
  fifth of the frame, with a semi-transparent background box for readability.
- `/concatenate` tries a fast stream-copy first; if the input videos don't
  share identical codecs/parameters, it automatically falls back to re-encoding.
