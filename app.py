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

# Bot koruması bypass için User Agent listesi
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0'
]

class VideoDownloader:
    def __init__(self):
        self.logger = logger

    def detect_platform(self, url):
        """URL'den platform türünü algılar"""
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'instagram.com' in url_lower or 'instagr.am' in url_lower:
            return 'instagram'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
            return 'facebook'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'twitter'
        return 'unknown'

    def clean_title(self, title):
        """Video başlığını temizler ve güvenli hale getirir"""
        if not title:
            return "video"
        return "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:50]

    def get_platform_specific_opts(self, platform, base_opts):
        """Platform'a özgü yt-dlp ayarlarını döndürür"""
        platform_opts = base_opts.copy()
        
        if platform == 'youtube':
            platform_opts.update({
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_skip': ['configs', 'webpage'],
                        'player_client': ['web'],
                        'innertube_host': 'studio.youtube.com',
                    }
                }
            })
        elif platform == 'instagram':
            platform_opts.update({
                'format': 'best[ext=mp4]/best',
                'extractor_args': {
                    'instagram': {
                        'api_key': None,
                    }
                }
            })
        elif platform == 'tiktok':
            platform_opts.update({
                'format': 'best[ext=mp4]/best',
                'extractor_args': {
                    'tiktok': {
                        'api_key': None,
                    }
                }
            })
        elif platform == 'facebook':
            platform_opts.update({
                'format': 'best[ext=mp4]/best',
                'extractor_args': {
                    'facebook': {
                        'api_key': None,
                    }
                }
            })
        
        return platform_opts

    def download_video(self, url, quality='best[height<=720]/best'):
        """Video indirme işlemini yönetir - Bot koruması bypass ile"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Platform algıla
            platform = self.detect_platform(url)
            self.logger.info(f"Platform algılandı: {platform} - URL: {url}")
            
            # Bot algılamasını bypass etmek için rastgele gecikme
            time.sleep(random.uniform(0.5, 2.0))
            
            # Temel yt-dlp ayarları
            base_opts = {
                'format': quality,
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'logger': self.YTDLLogger(self.logger),
                'max_filesize': MAX_CONTENT_LENGTH,
                
                # Bot koruması bypass ayarları
                'extractor_retries': 5,
                'fragment_retries': 5,
                'skip_unavailable_fragments': True,
                'ignoreerrors': False,
                
                # HTTP ayarları
                'http_headers': {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Accept-Encoding': 'gzip,deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                },
                
                # Güvenlik ve performans
                'no_check_certificate': True,
                'prefer_insecure': False,
                
                # Rate limiting
                'sleep_interval': 1,
                'max_sleep_interval': 5,
                'sleep_interval_requests': 1,
                
                # Format ayarları
                'format_sort': ['res:720', 'ext:mp4:m4a'],
                'format_sort_force': True,
                'merge_output_format': 'mp4',
            }
            
            # Platform'a özgü ayarları ekle
            ydl_opts = self.get_platform_specific_opts(platform, base_opts)
            
            # İlk deneme - normal indirme
            try:
                return self._attempt_download(url, ydl_opts, temp_dir)
            except yt_dlp.DownloadError as e:
                error_msg = str(e).lower()
                self.logger.warning(f"İlk deneme başarısız: {e}")
                
                # Bot algılanırsa alternatif yöntemleri dene
                if any(keyword in error_msg for keyword in ['sign in', 'bot', 'captcha', 'verify']):
                    self.logger.info("Bot algılandı, alternatif yöntem deneniyor...")
                    return self._try_alternative_methods(url, ydl_opts, temp_dir)
                elif 'format' in error_msg:
                    self.logger.info("Format hatası, fallback deneniyor...")
                    return self._try_format_fallback(url, ydl_opts, temp_dir)
                else:
                    raise e
                    
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _attempt_download(self, url, ydl_opts, temp_dir):
        """Temel indirme denemesi"""
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Önce info extract et
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("Video bilgileri alınamadı")
            
            title = self.clean_title(info.get('title'))
            ydl_opts['outtmpl'] = os.path.join(temp_dir, f'{title}.%(ext)s')
            
            # Download işlemi
            ydl.download([url])
            
            files = os.listdir(temp_dir)
            if not files:
                raise Exception("İndirme tamamlandı ama dosya bulunamadı")
                
            return os.path.join(temp_dir, files[0]), title

    def _try_alternative_methods(self, url, base_opts, temp_dir):
        """Bot algılandığında alternatif yöntemler"""
        alternative_methods = [
            # Method 1: En basit ayarlar
            {
                'format': 'worst[ext=mp4]/worst',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'http_headers': {
                    'User-Agent': random.choice(USER_AGENTS),
                },
                'extractor_retries': 1,
            },
            # Method 2: Farklı user agent ve minimal ayarlar
            {
                'format': 'best[height<=480][ext=mp4]/best[ext=mp4]',
                'quiet': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                },
                'no_check_certificate': True,
            },
            # Method 3: Format olmadan basit çıkarma
            {
                'skip_download': False,
                'format': 'best',
                'quiet': True,
                'ignoreerrors': True,
            }
        ]
        
        for i, method_opts in enumerate(alternative_methods):
            try:
                self.logger.info(f"Alternatif yöntem {i+1} deneniyor...")
                time.sleep(random.uniform(2.0, 5.0))  # Uzun bekleme
                
                method_opts['outtmpl'] = base_opts['outtmpl']
                method_opts['logger'] = base_opts['logger']
                method_opts['max_filesize'] = base_opts['max_filesize']
                
                return self._attempt_download(url, method_opts, temp_dir)
                
            except Exception as e:
                self.logger.warning(f"Alternatif yöntem {i+1} başarısız: {e}")
                continue
        
        raise Exception("Tüm alternatif yöntemler başarısız oldu. Video bot koruması nedeniyle indirilemedi.")

    def _try_format_fallback(self, url, base_opts, temp_dir):
        """Format hatası durumunda fallback formatları dene"""
        fallback_formats = [
            'best[ext=mp4]',
            'best[height<=480]',
            'best[height<=360]',
            'worst[ext=mp4]',
            'best/worst'
        ]
        
        for fmt in fallback_formats:
            try:
                self.logger.info(f"Format deneniyor: {fmt}")
                opts = base_opts.copy()
                opts['format'] = fmt
                
                return self._attempt_download(url, opts, temp_dir)
                
            except Exception as e:
                self.logger.warning(f"Format {fmt} başarısız: {e}")
                continue
        
        raise Exception("Hiçbir format çalışmadı")

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
        'version': '2.3',
        'status': 'running',
        'environment': 'Railway' if IS_RAILWAY else 'Local',
        'features': [
            'Bot detection bypass',
            'Multi-platform support',
            'Format fallback',
            'Rate limiting protection'
        ],
        'supported_platforms': [
            'YouTube', 'Instagram', 'TikTok', 
            'Facebook', 'Twitter/X', 'Generic'
        ],
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
        'yt_dlp_version': yt_dlp.version.__version__,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

@app.route('/download', methods=['POST'])
def download_video():
    start_time = time.time()
    
    try:
        # Request validation
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                'error': 'URL is required', 
                'success': False,
                'code': 'MISSING_URL'
            }), 400
        
        url = data['url'].strip()
        quality = data.get('quality', 'best[height<=720]/best')
        
        # URL validation
        if not url.startswith(('http://', 'https://')):
            return jsonify({
                'error': 'Invalid URL format', 
                'success': False,
                'code': 'INVALID_URL'
            }), 400
        
        logger.info(f"Download request - URL: {url}, Quality: {quality}")
        
        # Download işlemi
        downloader = VideoDownloader()
        file_path, title = downloader.download_video(url, quality)
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        
        processing_time = round(time.time() - start_time, 2)
        logger.info(f"Download successful - Title: {title}, Size: {file_size} bytes, Time: {processing_time}s")
        
        def generate():
            try:
                with open(file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Cleanup completed for: {title}")
        
        return Response(
            stream_with_context(generate()),
            content_type='video/mp4',
            headers={
                'Content-Length': str(file_size),
                'Content-Disposition': f'attachment; filename="{title}.mp4"',
                'Cache-Control': 'no-store, no-cache, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-Video-Title': title,
                'X-Processing-Time': str(processing_time),
                'X-File-Size': str(file_size)
            }
        )
        
    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        logger.error(f"yt-dlp download failed: {error_msg}")
        
        # Spesifik hata kodları
        if 'sign in' in error_msg.lower() or 'bot' in error_msg.lower():
            error_code = 'BOT_DETECTED'
            user_message = 'Video bot koruması nedeniyle indirilemedi. Lütfen farklı bir video deneyin.'
        elif 'format' in error_msg.lower():
            error_code = 'FORMAT_ERROR'
            user_message = 'Video formatı desteklenmiyor.'
        elif 'private' in error_msg.lower():
            error_code = 'PRIVATE_VIDEO'
            user_message = 'Bu video özel olarak ayarlanmış.'
        elif 'not available' in error_msg.lower():
            error_code = 'VIDEO_UNAVAILABLE'
            user_message = 'Video artık mevcut değil.'
        else:
            error_code = 'DOWNLOAD_ERROR'
            user_message = 'Video indirilemedi.'
        
        return jsonify({
            'error': user_message,
            'technical_error': error_msg,
            'success': False,
            'code': error_code,
            'processing_time': round(time.time() - start_time, 2)
        }), 400
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error: {error_msg}")
        
        return jsonify({
            'error': 'Beklenmeyen bir hata oluştu',
            'technical_error': error_msg,
            'success': False,
            'code': 'INTERNAL_ERROR',
            'processing_time': round(time.time() - start_time, 2)
        }), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        'error': 'Dosya çok büyük',
        'success': False,
        'code': 'FILE_TOO_LARGE'
    }), 413

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'error': 'Çok fazla istek. Lütfen bir süre bekleyin.',
        'success': False,
        'code': 'RATE_LIMITED'
    }), 429

# Uygulama Başlatma
if __name__ == '__main__':
    logger.info(f"Starting ReelDrop API v2.3 on port {PORT}")
    logger.info(f"Environment: {'Railway' if IS_RAILWAY else 'Local'}")
    logger.info(f"yt-dlp version: {yt_dlp.version.__version__}")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=not IS_RAILWAY,
        threaded=True
    )