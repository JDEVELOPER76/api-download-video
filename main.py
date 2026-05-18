from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
import yt_dlp
import os
import shutil
import logging
import tempfile
from glob import glob

app = FastAPI()
logger = logging.getLogger("uvicorn.error")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")


def check_ffmpeg_paths() -> tuple[str | None, str | None]:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    return ffmpeg_path, ffprobe_path


@app.on_event("startup")
async def validate_ffmpeg_on_startup():
    ffmpeg_path, ffprobe_path = check_ffmpeg_paths()
    if ffmpeg_path and ffprobe_path:
        logger.info("FFmpeg detectado: %s", ffmpeg_path)
        logger.info("FFprobe detectado: %s", ffprobe_path)
    else:
        logger.warning(
            "FFmpeg/ffprobe no detectados en PATH. Instala FFmpeg para fusionar video+audio y convertir a mp3."
        )


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/download")
async def download(data: dict):
    """
    Descarga video/audio desde URL usando yt-dlp
    Soporta formatos: best, 720p, audio
    """
    temp_dir = None
    try:
        ffmpeg_path, ffprobe_path = check_ffmpeg_paths()
        if not ffmpeg_path or not ffprobe_path:
            raise HTTPException(
                status_code=500,
                detail="FFmpeg no esta instalado o no esta en PATH. Instala FFmpeg y reinicia el servidor.",
            )

        url = data.get("url")
        fmt = data.get("format", "best")
        
        if not url:
            raise HTTPException(status_code=400, detail="URL es requerida")

        # Bloquear playlists explícitamente
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl_check:
            check_info = ydl_check.extract_info(url, download=False)

        if isinstance(check_info, dict) and (
            check_info.get("_type") in {"playlist", "multi_video"} or check_info.get("entries") is not None
        ):
            raise HTTPException(status_code=400, detail="No se permite descargar playlists. Usa URL de un solo video.")

        temp_dir = tempfile.mkdtemp(prefix="yt_dlp_")
        
        # Configurar opciones según el formato solicitado
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'noplaylist': True,
        }
        
        if fmt == "best":
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
            ydl_opts['merge_output_format'] = 'mp4'
        elif fmt == "720p":
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
            ydl_opts['merge_output_format'] = 'mp4'
        elif fmt == "audio":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        # Descargar con yt-dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            raw_filename = ydl.prepare_filename(info)

        # Resolver archivo final tras post-procesado con FFmpeg
        filepath = os.path.join(temp_dir, os.path.basename(raw_filename))
        stem = os.path.splitext(filepath)[0]

        if fmt == "audio":
            filepath = stem + ".mp3"
        elif fmt in {"best", "720p"}:
            filepath = stem + ".mp4"

        if not os.path.exists(filepath):
            matches = glob(stem + ".*")
            if matches:
                filepath = max(matches, key=os.path.getmtime)
        
        if not os.path.exists(filepath):
            raise HTTPException(status_code=500, detail="Archivo no encontrado después de descargar")
        
        # Retornar archivo y limpiar automáticamente al finalizar la respuesta
        return FileResponse(
            path=filepath,
            media_type='application/octet-stream',
            filename=os.path.basename(filepath),
            background=BackgroundTask(shutil.rmtree, temp_dir, True)
        )
    
    except HTTPException:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as e:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Error en descarga: {str(e)}")
