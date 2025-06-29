#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import tempfile
import shutil
import json
import base64
import random
import time
import traceback
import sys
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

# Log Yapılandırması - Railway için optimize
logging.basicConfig(
    level=logging.INFO,  # DEBUG yerine INFO (performans için)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
        # FileHandler kaldırıldı - Railway'de sorun çıkarır
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Ortam Değişkenleri
IS_RAILWAY = os.environ.get('RAILWAY_ENVIRONMENT', '').lower() == 'production'
PORT = int(os.environ.get('PORT', 8000))
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB

# Enhanced User Agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0'
]

class EnhancedVideoDownloader:
    def __init__(self):
        self.logger = logger
        self.logger.info("VideoDownloader initialized")

    def detect_platform(self, url):
        """URL'den platform türünü algılar"""
        url_lower = url.lower()
        platform = 'unknown'
        
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            platform = 'youtube'
        elif 'instagram.com' in url_lower or 'instagr.am' in url_lower:
            platform = 'instagram'
        elif 'tiktok.com' in url_lower:
            platform = 'tiktok'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
            platform = 'facebook'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            platform = 'twitter'
        
        self.logger.info(f"Platform detected: {platform} for URL: {url}")
        return platform

    def clean_title(self, title):
        """Video başlığını temizler"""
        if not title:
            return "video"
        cleaned = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:50]
        return cleaned

    def create_debug_opts(self, platform, quality):
        """Debug için minimal yt-dlp ayarları - YouTube bot bypass eklendi"""
        opts = {
            'format': quality,
            'quiet': True,  # Railway için sessiz mod
            'no_warnings': True,
            'logger': self.DebugLogger(self.logger),
            'max_filesize': MAX_CONTENT_LENGTH,
            'ignoreerrors': False,
            'no_check_certificate': True,
            'extract_flat': False,
            
            # Bot bypass için gelişmiş HTTP ayarları
            'http_headers': {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
            },
            
            # Retry ayarları - artırıldı
            'extractor_retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 60,
            
            # Bot bypass için gecikme
            'sleep_interval': 1,
            'max_sleep_interval': 3,
        }
        
        # Platform özel ayarlar - YouTube için gelişmiş bypass
        if platform == 'youtube':
            opts.update({
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],  # Daha agresif skip
                        'player_client': ['web', 'android'],  # Multiple clients
                        'player_skip': ['configs', 'webpage'],
                        'innertube_host': 'studio.youtube.com',
                    }
                },
                # YouTube için özel format seçimi
                'format_sort': ['res:720', 'ext:mp4:m4a'],
                'format_sort_force': True,
            })
        
        return opts

    def test_basic_extraction(self, url):
        """Temel bilgi çıkarma testi - YouTube için bypass eklendi"""
        try:
            self.logger.info(f"Testing basic extraction for: {url}")
            
            platform = self.detect_platform(url)
            
            # YouTube için özel test ayarları
            if platform == 'youtube':
                opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': False,
                    'skip_download': True,
                    'logger': self.DebugLogger(self.logger),
                    'outtmpl': {
                        'default': '%(title)s.%(ext)s'
                    },
                    # Minimal bot bypass
                    'http_headers': {
                        'User-Agent': random.choice(USER_AGENTS),
                        'Accept-Language': 'en-US,en;q=0.9',
                    },
                    'extractor_args': {
                        'youtube': {
                            'skip': ['dash'],
                            'player_client': ['web'],
                        }
                    },
                    'socket_timeout': 30,
                }
            else:
                # Diğer platformlar için normal ayarlar
                opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': False,
                    'skip_download': True,
                    'logger': self.DebugLogger(self.logger),
                    'outtmpl': {
                        'default': '%(title)s.%(ext)s'
                    }
                }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    self.logger.info(f"Basic extraction successful. Title: {info.get('title', 'Unknown')}")
                    return {
                        'success': True,
                        'title': info.get('title'),
                        'duration': info.get('duration'),
                        'formats_count': len(info.get('formats', [])),
                        'uploader': info.get('uploader'),
                    }
                else:
                    self.logger.error("Basic extraction returned None")
                    return {'success': False, 'error': 'No info extracted'}
                    
        except Exception as e:
            self.logger.error(f"Basic extraction failed: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_video(self, url, quality='best[height<=720]/best'):
        """Ana indirme fonksiyonu - YouTube bot bypass logic eklendi"""
        temp_dir = tempfile.mkdtemp()
        self.logger.info(f"Starting download process. URL: {url}")
        
        try:
            # 1. Platform algıla
            platform = self.detect_platform(url)
            
            # 2. YouTube için özel işlem
            if platform == 'youtube':
                return self._handle_youtube_download(url, quality, temp_dir)
            else:
                # 3. Diğer platformlar için normal işlem
                return self._handle_other_platform_download(url, quality, platform, temp_dir)
            
        except Exception as e:
            self.logger.error(f"Download process failed: {str(e)}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _handle_youtube_download(self, url, quality, temp_dir):
        """YouTube için özel bot bypass download logic"""
        self.logger.info("YouTube detected - using enhanced bot bypass")
        
        # YouTube için alternatif stratejiler
        strategies = [
            {
                'name': 'Minimal Stealth',
                'quality': 'worst[ext=mp4]/worst',
                'delay': 2
            },
            {
                'name': 'Standard Quality',
                'quality': 'best[height<=480][ext=mp4]/best[ext=mp4]',
                'delay': 3
            },
            {
                'name': 'Original Quality', 
                'quality': quality,
                'delay': 4
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"Trying YouTube strategy: {strategy['name']}")
                
                # Bot algılamasını geciktirmek için bekleme
                time.sleep(random.uniform(1, strategy['delay']))
                
                opts = self.create_debug_opts('youtube', strategy['quality'])
                opts['outtmpl'] = {
                    'default': os.path.join(temp_dir, '%(title)s.%(ext)s')
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Info extraction
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        raise Exception("Could not extract YouTube video info")
                    
                    title = self.clean_title(info.get('title', 'video'))
                    self.logger.info(f"YouTube video info extracted: {title}")
                    
                    # Download
                    opts['outtmpl'] = {
                        'default': os.path.join(temp_dir, f'{title}.%(ext)s')
                    }
                    
                    ydl.download([url])
                    
                    # Dosya kontrolü
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        file_size = os.path.getsize(file_path)
                        self.logger.info(f"YouTube download successful! Size: {file_size} bytes")
                        return file_path, title
                    
            except yt_dlp.DownloadError as e:
                error_msg = str(e).lower()
                if 'sign in' in error_msg or 'bot' in error_msg:
                    self.logger.warning(f"YouTube bot detection for strategy '{strategy['name']}', trying next...")
                    continue
                else:
                    self.logger.warning(f"YouTube strategy '{strategy['name']}' failed: {e}")
                    continue
            except Exception as e:
                self.logger.warning(f"YouTube strategy '{strategy['name']}' error: {e}")
                continue
        
        # Tüm YouTube stratejileri başarısız
        raise Exception("YouTube video protected by bot detection - please try a different video or platform")

    def _handle_other_platform_download(self, url, quality, platform, temp_dir):
        """Diğer platformlar için normal download - mevcut working logic"""
        # Temel çıkarma testi (mevcut kod)
        extraction_test = self.test_basic_extraction(url)
        if not extraction_test['success']:
            raise Exception(f"Basic extraction failed: {extraction_test['error']}")
        
        self.logger.info(f"Basic extraction test passed: {extraction_test}")
        
        # Download dene (mevcut kod)
        return self._attempt_download_with_debug(url, quality, platform, temp_dir)

    def _attempt_download_with_debug(self, url, quality, platform, temp_dir):
        """Debug bilgileri ile indirme denemesi - mevcut working code"""
        
        # Çeşitli kalite seçenekleri dene
        quality_options = [
            quality,  # Kullanıcının seçtiği
            'best[height<=720]/best',
            'best[height<=480]/best', 
            'best[ext=mp4]/best',
            'worst[ext=mp4]/worst',
            'best',
            'worst'
        ]
        
        for i, current_quality in enumerate(quality_options):
            try:
                self.logger.info(f"Attempting download with quality option {i+1}: {current_quality}")
                
                opts = self.create_debug_opts(platform, current_quality)
                opts['outtmpl'] = {
                    'default': os.path.join(temp_dir, '%(title)s.%(ext)s')
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # İlk olarak info al
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        raise Exception("Could not extract video info")
                    
                    title = self.clean_title(info.get('title', 'video'))
                    self.logger.info(f"Video info extracted successfully. Title: {title}")
                    
                    # Output template'i güncelle
                    opts['outtmpl'] = {
                        'default': os.path.join(temp_dir, f'{title}.%(ext)s')
                    }
                    
                    # Download yap
                    ydl.download([url])
                    
                    # Dosya kontrolü
                    files = os.listdir(temp_dir)
                    
                    if not files:
                        raise Exception("Download completed but no files found")
                    
                    file_path = os.path.join(temp_dir, files[0])
                    file_size = os.path.getsize(file_path)
                    
                    self.logger.info(f"Download successful! File: {files[0]}, Size: {file_size} bytes")
                    return file_path, title
                    
            except yt_dlp.DownloadError as e:
                error_msg = str(e).lower()
                self.logger.warning(f"Quality option {i+1} failed: {e}")
                
                # Spesifik hata analizi
                if 'sign in' in error_msg or 'bot' in error_msg:
                    self.logger.error("Bot detection encountered")
                    if i < len(quality_options) - 1:
                        self.logger.info("Trying next quality option...")
                        time.sleep(random.uniform(2, 5))  # Bot algılamasını geciktir
                        continue
                elif 'format' in error_msg:
                    self.logger.warning("Format error, trying next option")
                    continue
                elif 'private' in error_msg:
                    raise Exception("Video is private or unavailable")
                else:
                    self.logger.error(f"Unhandled yt-dlp error: {e}")
                    if i < len(quality_options) - 1:
                        continue
                        
            except Exception as e:
                self.logger.error(f"Unexpected error in attempt {i+1}: {e}")
                if i < len(quality_options) - 1:
                    continue
                else:
                    raise e
        
        # Tüm seçenekler başarısız
        raise Exception("All quality options failed. Video might be protected or unavailable.")

    class DebugLogger:
        """Railway için optimize edilmiş logger"""
        def __init__(self, logger):
            self.logger = logger
            
        def debug(self, msg):
            # Çok detaylı debug mesajlarını skip et
            pass
                
        def info(self, msg):
            # Sadece önemli info mesajları
            if 'ERROR' in str(msg):
                self.logger.warning(f"yt-dlp: {msg}")
                
        def warning(self, msg):
            self.logger.warning(f"yt-dlp: {msg}")
            
        def error(self, msg):
            self.logger.error(f"yt-dlp: {msg}")

# API Endpoints - Railway için optimize
@app.route('/')
def home():
    try:
        return jsonify({
            'service': 'ReelDrop API',
            'version': '2.4-railway',
            'status': 'running',
            'environment': 'Railway' if IS_RAILWAY else 'Local',
            'features': [
                'YouTube bot bypass',
                'Multiple platform support',
                'Enhanced error handling'
            ],
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Railway healthcheck endpoint - ultra minimal"""
    return "OK", 200

@app.route('/status')
def status():
    """Detailed status check"""
    try:
        return jsonify({
            'status': 'healthy',
            'yt_dlp_version': yt_dlp.version.__version__,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/test', methods=['POST'])
def test_video():
    """Video bilgi çıkarma testi"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL gerekli'}), 400
        
        url = data['url'].strip()
        
        downloader = EnhancedVideoDownloader()
        result = downloader.test_basic_extraction(url)
        
        return jsonify({
            'test_result': result,
            'url': url,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

@app.route('/download', methods=['POST'])
def download_video():
    start_time = time.time()
    request_id = f"req_{int(time.time())}"
    
    try:
        # Request validation
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'error': 'URL is required', 
                'success': False,
                'code': 'MISSING_URL',
                'request_id': request_id
            }), 400
        
        url = data['url'].strip()
        quality = data.get('quality', 'best[height<=720]/best')
        
        logger.info(f"[{request_id}] Processing URL: {url}")
        
        # URL validation
        if not url.startswith(('http://', 'https://')):
            return jsonify({
                'error': 'Invalid URL format', 
                'success': False,
                'code': 'INVALID_URL',
                'request_id': request_id
            }), 400
        
        # Download işlemi
        downloader = EnhancedVideoDownloader()
        file_path, title = downloader.download_video(url, quality)
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        processing_time = round(time.time() - start_time, 2)
        
        logger.info(f"[{request_id}] Download successful - Title: {title}, Size: {file_size} bytes")
        
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
                'Cache-Control': 'no-store, no-cache, must-revalidate',
                'X-Video-Title': title,
                'X-Processing-Time': str(processing_time),
                'X-Request-ID': request_id
            }
        )
        
    except Exception as e:
        processing_time = round(time.time() - start_time, 2)
        
        logger.error(f"[{request_id}] Download failed: {str(e)}")
        
        # Kullanıcı dostu hata mesajları
        error_msg = str(e).lower()
        if 'bot' in error_msg or 'sign in' in error_msg:
            user_message = 'YouTube video bot koruması nedeniyle indirilemedi'
            error_code = 'YOUTUBE_BOT_PROTECTION'
            suggestion = 'Instagram, TikTok veya Facebook videolarını deneyin'
        elif 'protected' in error_msg:
            user_message = 'Video korunuyor ve indirilemez'
            error_code = 'VIDEO_PROTECTED'
            suggestion = 'Farklı bir video deneyin'
        elif 'format' in error_msg:
            user_message = 'Video formatı desteklenmiyor'
            error_code = 'FORMAT_ERROR'
            suggestion = 'Farklı kalite seçeneği deneyin'
        elif 'private' in error_msg or 'unavailable' in error_msg:
            user_message = 'Video mevcut değil veya özel'
            error_code = 'VIDEO_UNAVAILABLE'
            suggestion = 'Video URL\'sini kontrol edin'
        else:
            user_message = 'Video indirilemedi'
            error_code = 'DOWNLOAD_ERROR'
            suggestion = 'Farklı bir platform veya video deneyin'
        
        return jsonify({
            'error': user_message,
            'success': False,
            'code': error_code,
            'suggestion': suggestion,
            'request_id': request_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

# Railway için optimize edilmiş startup
if __name__ == '__main__':
    logger.info(f"Starting ReelDrop API on port {PORT}")
    logger.info(f"Environment: {'Railway' if IS_RAILWAY else 'Local'}")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,         # Her zaman False (Railway için)
        threaded=True,
        use_reloader=False   # Railway için
    )