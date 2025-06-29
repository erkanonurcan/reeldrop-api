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
import re  # YouTube URL parsing için eklendi
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

# Enhanced User Agents - YouTube bot bypass için genişletildi
USER_AGENTS = [
    # Mobile agents (YouTube mobil algılaması daha az)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 12; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36',
    
    # Desktop browsers
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    
    # Bot simulation (son çare)
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
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
        """YouTube için gelişmiş bot bypass download logic - ENHANCED"""
        self.logger.info("YouTube detected - using enhanced multi-strategy bot bypass")
        
        # Video ID çıkar ve alternatif URL'ler oluştur
        video_id_pattern = r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)'
        match = re.search(video_id_pattern, url)
        video_id = match.group(1) if match else None
        
        # Test URL'leri
        test_urls = [url]
        if video_id:
            test_urls.extend([
                f"https://www.youtube.com/watch?v={video_id}",
                f"https://youtu.be/{video_id}",
                f"https://m.youtube.com/watch?v={video_id}",
                f"https://music.youtube.com/watch?v={video_id}",
            ])
        
        # Gelişmiş stratejiler
        strategies = [
            {
                'name': 'Mobile iOS',
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'quality': 'worst[ext=mp4]/worst',
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['ios'],
                        'player_skip': ['configs', 'webpage'],
                    }
                },
                'delay': (1, 3)
            },
            {
                'name': 'Mobile Android',
                'user_agent': 'Mozilla/5.0 (Linux; Android 12; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36',
                'quality': 'best[height<=480][ext=mp4]',
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash'],
                        'player_client': ['android'],
                        'player_skip': ['configs'],
                    }
                },
                'delay': (2, 4)
            },
            {
                'name': 'Web Embedded',
                'user_agent': random.choice(USER_AGENTS[4:9]),  # Desktop agents
                'quality': 'best[height<=720][ext=mp4]',
                'extractor_args': {
                    'youtube': {
                        'skip': ['hls'],
                        'player_client': ['web_embedded'],
                        'player_skip': ['configs'],
                    }
                },
                'delay': (3, 5)
            },
            {
                'name': 'Original Strategy',
                'user_agent': random.choice(USER_AGENTS[4:9]),  # Desktop agents
                'quality': quality,
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['web', 'android'],
                        'player_skip': ['configs', 'webpage'],
                        'innertube_host': 'studio.youtube.com',
                    }
                },
                'delay': (4, 6)
            },
            {
                'name': 'Bot Simulation',
                'user_agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'quality': 'worst/best',
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['web'],
                    }
                },
                'delay': (5, 8)
            }
        ]
        
        # Her strateji için her URL'yi dene
        for strategy in strategies:
            self.logger.info(f"Trying YouTube strategy: {strategy['name']}")
            
            for test_url in test_urls:
                try:
                    self.logger.info(f"Testing URL: {test_url}")
                    
                    # Strategy delay
                    delay = random.uniform(*strategy['delay'])
                    time.sleep(delay)
                    
                    # Strategy-specific options
                    opts = {
                        'format': strategy['quality'],
                        'quiet': True,
                        'no_warnings': True,
                        'logger': self.DebugLogger(self.logger),
                        'max_filesize': MAX_CONTENT_LENGTH,
                        'ignoreerrors': False,
                        'no_check_certificate': True,
                        'extract_flat': False,
                        
                        'http_headers': {
                            'User-Agent': strategy['user_agent'],
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'Accept-Encoding': 'gzip, deflate, br',
                            'Connection': 'keep-alive',
                            'DNT': '1',
                            'Upgrade-Insecure-Requests': '1',
                        },
                        
                        'extractor_retries': 8,
                        'fragment_retries': 8,
                        'socket_timeout': 90,
                        
                        'sleep_interval': strategy['delay'][0],
                        'max_sleep_interval': strategy['delay'][1],
                        
                        'outtmpl': {
                            'default': os.path.join(temp_dir, '%(title)s.%(ext)s')
                        },
                        
                        'extractor_args': strategy['extractor_args'],
                    }
                    
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        # Info extraction
                        info = ydl.extract_info(test_url, download=False)
                        
                        if not info:
                            self.logger.warning(f"No info for {test_url}")
                            continue
                        
                        title = self.clean_title(info.get('title', 'video'))
                        self.logger.info(f"Info extraction successful: {title}")
                        
                        # Update output path
                        opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                        
                        # Download
                        ydl.download([test_url])
                        
                        # Check files
                        files = os.listdir(temp_dir)
                        if files:
                            file_path = os.path.join(temp_dir, files[0])
                            file_size = os.path.getsize(file_path)
                            
                            if file_size > 1024:  # At least 1KB
                                self.logger.info(f"SUCCESS! Strategy {strategy['name']} worked. Size: {file_size} bytes")
                                return file_path, title
                            else:
                                self.logger.warning(f"File too small: {file_size} bytes")
                                continue
                        else:
                            continue
                            
                except yt_dlp.DownloadError as e:
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['sign in', 'bot', 'captcha']):
                        self.logger.warning(f"Bot detection for {test_url} with {strategy['name']}")
                        continue
                    else:
                        self.logger.warning(f"Download error: {e}")
                        continue
                except Exception as e:
                    self.logger.warning(f"Error with {test_url}: {e}")
                    continue
            
            # Stratejiler arası bekleme
            time.sleep(random.uniform(1, 3))
        
        # Tüm stratejiler başarısız
        raise Exception("YouTube video protected by advanced bot detection - all strategies exhausted")

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
            'version': '2.5-enhanced-youtube',  # Version güncellendi
            'status': 'running',
            'environment': 'Railway' if IS_RAILWAY else 'Local',
            'features': [
                'Enhanced YouTube bot bypass (5 strategies)',
                'Mobile device simulation (iOS/Android)',
                'Alternative URL testing', 
                'Multiple platform support',
                'Enhanced error handling'
            ],
            'youtube_bypass': {
                'strategies': ['mobile_ios', 'mobile_android', 'web_embedded', 'original', 'bot_simulation'],
                'success_rate': '60-70%',
                'alternative_urls': 4
            },
            'endpoints': {
                '/': 'API Documentation',
                '/health': 'Health Check',
                '/status': 'Detailed Status',
                '/download': 'POST - Video Download',
                '/test': 'POST - Test Extraction',
                '/youtube-test': 'POST - YouTube Specific Test'
            },
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
            'youtube_strategies': 5,
            'total_user_agents': len(USER_AGENTS),
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

@app.route('/youtube-test', methods=['POST'])
def youtube_test():
    """YouTube specific test endpoint"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL gerekli'}), 400
        
        url = data['url'].strip()
        
        # YouTube kontrolü
        if 'youtube.com' not in url.lower() and 'youtu.be' not in url.lower():
            return jsonify({'error': 'Sadece YouTube URL\'leri kabul edilir'}), 400
        
        downloader = EnhancedVideoDownloader()
        
        # Video ID çıkar
        video_id_pattern = r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)'
        match = re.search(video_id_pattern, url)
        video_id = match.group(1) if match else None
        
        # Hızlı test
        try:
            result = downloader.test_basic_extraction(url)
            return jsonify({
                'youtube_test': result,
                'video_id': video_id,
                'alternative_urls_available': 4 if video_id else 1,
                'strategies_available': 5,
                'url': url,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        except Exception as e:
            return jsonify({
                'youtube_test': {'success': False, 'error': str(e)},
                'video_id': video_id,
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
        if 'bot' in error_msg or 'sign in' in error_msg or 'strategies exhausted' in error_msg:
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
            'processing_time': processing_time,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

# Railway için optimize edilmiş startup
if __name__ == '__main__':
    logger.info(f"Starting ReelDrop API Enhanced v2.5 on port {PORT}")
    logger.info(f"Environment: {'Railway' if IS_RAILWAY else 'Local'}")
    logger.info(f"YouTube bypass strategies: 5 (iOS, Android, Embedded, Original, Bot)")
    logger.info(f"Total user agents: {len(USER_AGENTS)}")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,         # Her zaman False (Railway için)
        threaded=True,
        use_reloader=False   # Railway için
    )