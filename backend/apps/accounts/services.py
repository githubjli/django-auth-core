import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile


DEFAULT_THUMBNAIL_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn4n/4AAAAASUVORK5CYII='
)


def generate_video_thumbnail(video, time_offset: float = 1.0) -> bool:
    if not video.file:
        return False

    thumbnail_content = _extract_thumbnail_with_ffmpeg(video, time_offset=time_offset)
    if thumbnail_content is None:
        thumbnail_content = ContentFile(DEFAULT_THUMBNAIL_PNG)

    filename = f'video_{video.pk or "new"}_{uuid4().hex}.png'
    if video.thumbnail:
        video.thumbnail.delete(save=False)
    video.thumbnail.save(filename, thumbnail_content, save=False)
    return True


def _extract_thumbnail_with_ffmpeg(video, time_offset: float):
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        return None

    try:
        input_path = Path(video.file.path)
    except (NotImplementedError, ValueError):
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / 'thumbnail.png'
        for offset in (max(time_offset, 0), 0):
            completed = subprocess.run(
                [
                    ffmpeg_path,
                    '-y',
                    '-ss',
                    str(offset),
                    '-i',
                    str(input_path),
                    '-frames:v',
                    '1',
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return ContentFile(output_path.read_bytes())

    return None
