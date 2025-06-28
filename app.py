#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import tempfile
import shutil
import json
import base64
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

# Log Yapılandırması
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Ortam Değişkenleri
IS_RAILWAY = os.environ.get('RAILWAY_ENVIRONMENT', '').lower() == 'production'
PORT = int(os.environ.get('PORT', 8000))
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB maksimum istek boyutu

class VideoDownloader:
    def __init__(self):
        self.logger = logger

    def clean_title(self, title):
        """Video başlığını temizler ve güvenli hale getirir"""
        if not title:
            return "video"
        return "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:50]

    def download_video(self, url, quality='best[ext=mp4]/best'):
        """Video indirme işlemini yönetir"""
        temp_dir = tempfile.mkdtemp()
        try:
            ydl_opts = {
                'format': quality,
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'logger': self.YTDLLogger(self.logger),
                'max_filesize': MAX_CONTENT_LENGTH
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = self.clean_title(info.get('title'))
                ydl_opts['outtmpl'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                ydl.download([url])
                
                files = os.listdir(temp_dir)
                if not files:
                    raise Exception("No files downloaded")
                    
                return os.path.join(temp_dir, files[0]), title
                
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    class YTDLLogger:
        """yt-dlp için özel logger"""
        def __init__(self, logger):
            self.logger = logger
            
        def debug(self, msg):
            if msg.startswith('[debug]'):
                pass
            else:
                self.logger.debug(f"yt-dlp: {msg}")
                
        def warning(self, msg):
            self.logger.warning(f"yt-dlp: {msg}")
            
        def error(self, msg):
            self.logger.error(f"yt-dlp: {msg}")

# API Endpoint'leri
@app.route('/')
def home():
    return jsonify({
        'service': 'ReelDrop API',
        'version': '2.2',
        'status': 'running',
        'environment': 'Railway' if IS_RAILWAY else 'Local',
        'endpoints': {
            '/': 'API Documentation',
            '/health': 'System Health Check',
            '/download': 'POST - Video Download'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'environment': 'Railway' if IS_RAILWAY else 'Local',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required', 'success': False}), 400
            
        downloader = VideoDownloader()
        file_path, title = downloader.download_video(
            data['url'],
            data.get('quality', 'best[ext=mp4]/best')
        )
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        
        def generate():
            try:
                with open(file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        
        return Response(
            stream_with_context(generate()),
            content_type='video/mp4',
            headers={
                'Content-Length': str(file_size),
                'Content-Disposition': f'attachment; filename="{title}.mp4"',
                'Cache-Control': 'no-store',
                'X-Video-Title': title
            }
        )
        
    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

# Uygulama Başlatma
if __name__ == '__main__':
    logger.info(f"Starting server on port {PORT}")
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=not IS_RAILWAY,
        threaded=True
    )