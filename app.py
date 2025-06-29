#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import tempfile
import shutil
import json
import random
import time
import sys
import re
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

# Minimal logging
logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Railway optimized settings
IS_RAILWAY = os.environ.get('RAILWAY_ENVIRONMENT', '').lower() == 'production'
PORT = int(os.environ.get('PORT', 8000))
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB limit to prevent timeout

# Timeout settings
DOWNLOAD_TIMEOUT = 120  # 2 minutes max
EXTRACTION_TIMEOUT = 30  # 30 seconds max

USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 12; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

class TimeoutError(Exception):
    pass

class QuickDownloader:
    def __init__(self):
        self.logger = logger
        self.result = None
        self.error = None

    def download_with_timeout(self, url, quality, timeout=DOWNLOAD_TIMEOUT):
        """Timeout ile indirme"""
        def download_worker():
            try:
                self.result = self._quick_download(url, quality)
            except Exception as e:
                self.error = e

        thread = threading.Thread(target=download_worker)
        thread.daemon = True
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            # Thread hala çalışıyor, timeout oldu
            raise TimeoutError(f"Download timeout after {timeout} seconds")
        
        if self.error:
            raise self.error
            
        return self.result

    def _quick_download(self, url, quality):
        temp_dir = tempfile.mkdtemp()
        
        try:
            if 'youtube' in url.lower():
                return self._youtube_quick(url, quality, temp_dir)
            else:
                return self._other_quick(url, quality, temp_dir)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _youtube_quick(self, url, quality, temp_dir):
        """Hızlı YouTube indirme - sadece 2 strateji"""
        strategies = [
            {
                'name': 'Mobile',
                'quality': 'worst[ext=mp4]/worst',
                'agent': USER_AGENTS[0],
                'args': {'youtube': {'skip': ['dash', 'hls'], 'player_client': ['ios']}}
            },
            {
                'name': 'Desktop',  
                'quality': 'best[height<=480]/best',
                'agent': USER_AGENTS[2],
                'args': {'youtube': {'skip': ['dash'], 'player_client': ['web']}}
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"YouTube strategy: {strategy['name']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {'User-Agent': strategy['agent']},
                    'extractor_args': strategy['args'],
                    'socket_timeout': 20,
                    'extractor_retries': 2,
                    'fragment_retries': 2,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')}
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Quick info extraction with timeout
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    title = self._clean_title(info.get('title', 'video'))
                    
                    # Update output path
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    # Download
                    ydl.download([url])
                    
                    # Check file
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"Strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All YouTube strategies failed")

    def _other_quick(self, url, quality, temp_dir):
        """Diğer platformlar için hızlı indirme"""
        opts = {
            'format': quality,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)},
            'socket_timeout': 20,
            'extractor_retries': 2,
            'max_filesize': MAX_CONTENT_LENGTH,
            'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')}
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise Exception("Could not extract video info")
                
            title = self._clean_title(info.get('title', 'video'))
            opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
            
            ydl.download([url])
            
            files = os.listdir(temp_dir)
            if files:
                return os.path.join(temp_dir, files[0]), title
                
        raise Exception("Download failed")

    def _clean_title(self, title):
        if not title:
            return "video"
        return "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:30]

# API Endpoints
@app.route('/')
def home():
    return jsonify({
        'service': 'ReelDrop API',
        'version': '2.6-timeout-fixed',
        'status': 'running',
        'max_download_time': f'{DOWNLOAD_TIMEOUT}s',
        'max_file_size': f'{MAX_CONTENT_LENGTH // (1024*1024)}MB',
        'features': ['Fast YouTube bypass', 'Timeout protection', 'Memory optimization']
    })

@app.route('/health')
def health():
    return "OK", 200

@app.route('/download', methods=['POST'])
def download_video():
    start_time = time.time()
    request_id = f"req_{int(time.time())}"
    
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL required', 'request_id': request_id}), 400
        
        url = data['url'].strip()
        quality = data.get('quality', 'best[height<=720]/best')
        
        logger.info(f"[{request_id}] Download started: {url}")
        
        # URL validation
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'Invalid URL', 'request_id': request_id}), 400
        
        # Download with timeout
        downloader = QuickDownloader()
        
        try:
            file_path, title = downloader.download_with_timeout(url, quality, DOWNLOAD_TIMEOUT)
        except TimeoutError:
            return jsonify({
                'error': f'Download timeout after {DOWNLOAD_TIMEOUT} seconds',
                'code': 'TIMEOUT',
                'suggestion': 'Try a shorter video or lower quality',
                'request_id': request_id
            }), 408
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        processing_time = round(time.time() - start_time, 2)
        
        logger.info(f"[{request_id}] Success: {title} ({file_size} bytes, {processing_time}s)")
        
        # Streaming response with cleanup
        def generate():
            try:
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        yield chunk
            finally:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
        
        return Response(
            stream_with_context(generate()),
            content_type='video/mp4',
            headers={
                'Content-Length': str(file_size),
                'Content-Disposition': f'attachment; filename="{title}.mp4"',
                'Cache-Control': 'no-cache',
                'X-Processing-Time': str(processing_time),
                'X-Request-ID': request_id
            }
        )
        
    except Exception as e:
        processing_time = round(time.time() - start_time, 2)
        logger.error(f"[{request_id}] Error: {str(e)} ({processing_time}s)")
        
        # User-friendly error messages
        error_msg = str(e).lower()
        if 'timeout' in error_msg:
            user_message = 'Video indirme zaman aşımına uğradı'
            error_code = 'TIMEOUT'
        elif 'bot' in error_msg or 'sign in' in error_msg:
            user_message = 'YouTube bot koruması aktif'
            error_code = 'BOT_PROTECTION'
        elif 'too large' in error_msg or 'file size' in error_msg:
            user_message = 'Video çok büyük'
            error_code = 'FILE_TOO_LARGE'
        else:
            user_message = 'Video indirilemedi'
            error_code = 'DOWNLOAD_ERROR'
        
        return jsonify({
            'error': user_message,
            'code': error_code,
            'processing_time': processing_time,
            'request_id': request_id,
            'suggestion': 'Daha kısa video veya farklı platform deneyin'
        }), 500

# Railway timeout protection
@app.before_request
def before_request():
    # Set request timeout
    request.environ.setdefault('wsgi.url_scheme', 'https')

if __name__ == '__main__':
    logger.info(f"Starting ReelDrop API v2.6 on port {PORT}")
    logger.info(f"Download timeout: {DOWNLOAD_TIMEOUT}s")
    logger.info(f"Max file size: {MAX_CONTENT_LENGTH // (1024*1024)}MB")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )