#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import tempfile
import shutil
import json
import random
import time
import traceback
import sys
import requests
import re
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

# Log Yapılandırması
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Ortam Değişkenleri
IS_RAILWAY = os.environ.get('RAILWAY_ENVIRONMENT', '').lower() == 'production'
PORT = int(os.environ.get('PORT', 8000))
MAX_CONTENT_LENGTH = 100 * 1024 * 1024

# Ultra Enhanced User Agents - Daha çeşitli
RESIDENTIAL_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
]

# Free proxy listesi (isteğe bağlı - çalışan proxy'ler eklenebilir)
FREE_PROXIES = [
    # Buraya çalışan free proxy'ler eklenebilir
    # Format: {'type': 'http', 'proxy': 'ip:port', 'auth': None}
]

class YouTubeUltimateBypass:
    def __init__(self):
        self.logger = logger
        self.session_cookies = {}
        self.failed_strategies = set()
        self.logger.info("YouTube Ultimate Bypass initialized")

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
        """Video başlığını temizler"""
        if not title:
            return "video"
        cleaned = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:50]
        return cleaned

    def get_youtube_strategies(self):
        """YouTube için farklı bypass stratejileri"""
        return [
            {
                'name': 'mobile_stealth',
                'description': 'Mobile device simulation',
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'quality': 'worst[ext=mp4]/worst',
                'headers': {
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['android'],
                        'player_skip': ['configs', 'webpage'],
                    }
                },
                'delay': (2, 4)
            },
            {
                'name': 'desktop_minimal',
                'description': 'Minimal desktop browser',
                'user_agent': random.choice(RESIDENTIAL_USER_AGENTS),
                'quality': 'best[height<=480][ext=mp4]/best[height<=360][ext=mp4]',
                'headers': {
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash'],
                        'player_client': ['web'],
                    }
                },
                'delay': (3, 6)
            },
            {
                'name': 'embedded_bypass',
                'description': 'Embedded player simulation',
                'user_agent': random.choice(RESIDENTIAL_USER_AGENTS),
                'quality': 'best[height<=720][ext=mp4]',
                'headers': {
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.youtube.com/',
                    'Origin': 'https://www.youtube.com',
                    'X-YouTube-Client-Name': '1',
                    'X-YouTube-Client-Version': '2.20231201.01.00',
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['hls'],
                        'player_client': ['web', 'android'],
                        'player_skip': ['configs'],
                        'innertube_host': 'www.youtube.com',
                    }
                },
                'delay': (4, 8)
            },
            {
                'name': 'tv_client',
                'description': 'YouTube TV client simulation',
                'user_agent': 'Mozilla/5.0 (Linux; U; Android 10; SM-G973F Build/QP1A.190711.020) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/112.0.0.0 Mobile Safari/537.36 SmartTubeNext',
                'quality': 'best[height<=1080][ext=mp4]',
                'headers': {
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US',
                    'Content-Type': 'application/json',
                    'X-YouTube-Client-Name': '2',
                    'X-YouTube-Client-Version': '2.20231201',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv'],
                        'skip': ['dash', 'hls'],
                        'innertube_host': 'www.youtube.com',
                        'innertube_key': None,
                    }
                },
                'delay': (5, 10)
            },
            {
                'name': 'music_client',
                'description': 'YouTube Music client',
                'user_agent': random.choice(RESIDENTIAL_USER_AGENTS),
                'quality': 'best[ext=mp4]/best',
                'headers': {
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://music.youtube.com/',
                    'Origin': 'https://music.youtube.com',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android_music'],
                        'skip': ['dash'],
                    }
                },
                'delay': (6, 12)
            }
        ]

    def get_alternative_youtube_urls(self, original_url):
        """YouTube URL'si için alternatif URL'ler"""
        video_id_pattern = r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)'
        match = re.search(video_id_pattern, original_url)
        
        if not match:
            return [original_url]
        
        video_id = match.group(1)
        
        alternatives = [
            original_url,
            f"https://www.youtube.com/watch?v={video_id}",
            f"https://youtu.be/{video_id}",
            f"https://m.youtube.com/watch?v={video_id}",
            f"https://music.youtube.com/watch?v={video_id}",
            f"https://www.youtube.com/embed/{video_id}",
        ]
        
        return alternatives

    def create_stealth_opts(self, strategy):
        """Stealth yt-dlp options oluştur"""
        opts = {
            'format': strategy['quality'],
            'quiet': True,  # Minimize logging
            'no_warnings': True,
            'extract_flat': False,
            'logger': self.StealthLogger(self.logger),
            'max_filesize': MAX_CONTENT_LENGTH,
            'ignoreerrors': False,
            'no_check_certificate': True,
            
            # Enhanced HTTP simulation
            'http_headers': {
                'User-Agent': strategy['user_agent'],
                **strategy['headers']
            },
            
            # Aggressive retry settings
            'extractor_retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 120,
            
            # Rate limiting to avoid detection
            'sleep_interval': strategy['delay'][0],
            'max_sleep_interval': strategy['delay'][1],
            'sleep_interval_requests': 2,
            
            # Output template
            'outtmpl': {
                'default': '%(title)s.%(ext)s'
            },
            
            # Strategy-specific extractor args
            'extractor_args': strategy['extractor_args'],
            
            # Additional stealth settings
            'prefer_insecure': False,
            'no_call_home': True,
        }
        
        return opts

    def download_video(self, url, quality='best[height<=720]/best'):
        """Ana indirme fonksiyonu"""
        temp_dir = tempfile.mkdtemp()
        self.logger.info(f"Starting ultimate bypass download. URL: {url}")
        
        try:
            platform = self.detect_platform(url)
            
            if platform == 'youtube':
                return self._handle_youtube_ultimate_bypass(url, quality, temp_dir)
            else:
                return self._handle_other_platform(url, quality, platform, temp_dir)
                
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _handle_youtube_ultimate_bypass(self, url, quality, temp_dir):
        """YouTube için ultimate bypass"""
        self.logger.info("Starting YouTube ultimate bypass with multiple strategies")
        
        strategies = self.get_youtube_strategies()
        alternative_urls = self.get_alternative_youtube_urls(url)
        
        # Her strateji için her URL'yi dene
        for strategy in strategies:
            strategy_id = strategy['name']
            
            # Daha önce başarısız olan stratejileri atla
            if strategy_id in self.failed_strategies:
                self.logger.info(f"Skipping previously failed strategy: {strategy_id}")
                continue
            
            self.logger.info(f"Trying strategy: {strategy['description']}")
            
            for alt_url in alternative_urls:
                try:
                    self.logger.info(f"Testing URL: {alt_url} with strategy: {strategy_id}")
                    
                    # Strategy delay
                    delay = random.uniform(*strategy['delay'])
                    self.logger.info(f"Applying delay: {delay:.2f} seconds")
                    time.sleep(delay)
                    
                    opts = self.create_stealth_opts(strategy)
                    opts['outtmpl']['default'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
                    
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        # Info extraction test
                        self.logger.info("Testing info extraction...")
                        info = ydl.extract_info(alt_url, download=False)
                        
                        if not info:
                            self.logger.warning(f"No info extracted for {alt_url}")
                            continue
                        
                        title = self.clean_title(info.get('title', 'video'))
                        duration = info.get('duration', 0)
                        
                        self.logger.info(f"Info extraction successful: {title} ({duration}s)")
                        
                        # Update output template with title
                        opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                        
                        # Actual download
                        self.logger.info("Starting download...")
                        ydl.download([alt_url])
                        
                        # Check for downloaded files
                        files = os.listdir(temp_dir)
                        if files:
                            file_path = os.path.join(temp_dir, files[0])
                            file_size = os.path.getsize(file_path)
                            
                            if file_size > 1024:  # At least 1KB
                                self.logger.info(f"SUCCESS! Strategy {strategy_id} worked. File: {file_size} bytes")
                                return file_path, title
                            else:
                                self.logger.warning(f"File too small: {file_size} bytes")
                                continue
                        else:
                            self.logger.warning("No files found after download")
                            continue
                            
                except yt_dlp.DownloadError as e:
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['sign in', 'bot', 'captcha', 'verify']):
                        self.logger.warning(f"Bot detection for {alt_url} with {strategy_id}")
                        continue
                    else:
                        self.logger.warning(f"Download error for {alt_url}: {e}")
                        continue
                except Exception as e:
                    self.logger.warning(f"Unexpected error for {alt_url} with {strategy_id}: {e}")
                    continue
            
            # Mark strategy as failed if all URLs failed
            self.failed_strategies.add(strategy_id)
            self.logger.warning(f"Strategy {strategy_id} failed for all URLs")
        
        # All strategies failed
        raise Exception("All YouTube bypass strategies exhausted. Video is heavily protected or unavailable.")

    def _handle_other_platform(self, url, quality, platform, temp_dir):
        """Diğer platformlar için normal işlem"""
        try:
            opts = {
                'format': quality,
                'quiet': False,
                'no_warnings': False,
                'logger': self.StealthLogger(self.logger),
                'max_filesize': MAX_CONTENT_LENGTH,
                'http_headers': {
                    'User-Agent': random.choice(RESIDENTIAL_USER_AGENTS),
                },
                'outtmpl': {
                    'default': os.path.join(temp_dir, '%(title)s.%(ext)s')
                }
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info and info.get('title'):
                    title = self.clean_title(info.get('title'))
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        return file_path, title
                        
            raise Exception("Download completed but no files found")
            
        except Exception as e:
            raise Exception(f"Platform download failed: {e}")

    class StealthLogger:
        """Minimal stealth logger"""
        def __init__(self, logger):
            self.logger = logger
            
        def debug(self, msg):
            # Suppress most debug messages
            pass
                
        def info(self, msg):
            if 'ERROR' in str(msg) or 'WARNING' in str(msg):
                self.logger.warning(f"yt-dlp: {msg}")
                
        def warning(self, msg):
            self.logger.warning(f"yt-dlp: {msg}")
            
        def error(self, msg):
            self.logger.error(f"yt-dlp: {msg}")

# API Endpoints
@app.route('/')
def home():
    """Ana endpoint - Railway tarafından da kullanılabilir"""
    try:
        return jsonify({
            'service': 'ReelDrop API',
            'version': '3.0-ultimate',
            'status': 'running',
            'environment': 'Railway' if IS_RAILWAY else 'Local',
            'youtube_bypass': 'ultimate',
            'strategies': ['mobile_stealth', 'desktop_minimal', 'embedded_bypass', 'tv_client', 'music_client'],
            'features': [
                'Ultimate YouTube bot bypass',
                'Multiple strategy fallback',
                'Alternative URL testing',
                'Enhanced stealth headers',
                'Smart delay system'
            ],
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        logger.error(f"Home endpoint failed: {e}")
        return jsonify({
            'service': 'ReelDrop API',
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

@app.route('/health')
def health():
    """Railway healthcheck endpoint"""
    try:
        return jsonify({
            'status': 'healthy',
            'youtube_strategies': len(YouTubeUltimateBypass().get_youtube_strategies()),
            'yt_dlp_version': yt_dlp.version.__version__,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

@app.route('/download', methods=['POST'])
def download_video():
    start_time = time.time()
    request_id = f"req_{int(time.time())}"
    
    logger.info(f"[{request_id}] Ultimate bypass download request")
    
    try:
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
        
        if not url.startswith(('http://', 'https://')):
            return jsonify({
                'error': 'Invalid URL format', 
                'success': False,
                'code': 'INVALID_URL',
                'request_id': request_id
            }), 400
        
        # Ultimate bypass downloader
        downloader = YouTubeUltimateBypass()
        file_path, title = downloader.download_video(url, quality)
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        processing_time = round(time.time() - start_time, 2)
        
        logger.info(f"[{request_id}] Ultimate bypass SUCCESS! Title: {title}, Size: {file_size}, Time: {processing_time}s")
        
        def generate():
            try:
                with open(file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"[{request_id}] Cleanup completed")
        
        return Response(
            stream_with_context(generate()),
            content_type='video/mp4',
            headers={
                'Content-Length': str(file_size),
                'Content-Disposition': f'attachment; filename="{title}.mp4"',
                'Cache-Control': 'no-store, no-cache, must-revalidate',
                'X-Video-Title': title,
                'X-Processing-Time': str(processing_time),
                'X-Request-ID': request_id,
                'X-Bypass-Method': 'ultimate'
            }
        )
        
    except Exception as e:
        processing_time = round(time.time() - start_time, 2)
        error_details = {
            'error_type': type(e).__name__,
            'error_message': str(e),
            'processing_time': processing_time,
            'request_id': request_id
        }
        
        logger.error(f"[{request_id}] Ultimate bypass failed: {error_details}")
        
        # Enhanced error messages
        error_msg = str(e).lower()
        if 'exhausted' in error_msg or 'protected' in error_msg:
            user_message = 'YouTube videosu çok güçlü koruma altında'
            error_code = 'YOUTUBE_ULTRA_PROTECTED'
            suggestion = 'Bu video şu anda indirilemez. Instagram, TikTok veya Facebook videolarını deneyin.'
        elif 'bot' in error_msg or 'sign in' in error_msg:
            user_message = 'YouTube bot algılaması aktif'
            error_code = 'YOUTUBE_BOT_ACTIVE'
            suggestion = 'Lütfen 10-15 dakika bekleyip tekrar deneyin'
        else:
            user_message = 'Video indirme başarısız'
            error_code = 'DOWNLOAD_FAILED'
            suggestion = 'Farklı bir platform videosunu deneyin'
        
        return jsonify({
            'error': user_message,
            'success': False,
            'code': error_code,
            'suggestion': suggestion,
            'debug_info': error_details,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

if __name__ == '__main__':
    logger.info(f"Starting ReelDrop API v3.0-ultimate on port {PORT}")
    logger.info("YouTube Ultimate Bypass System initialized")
    logger.info(f"Available strategies: {len(YouTubeUltimateBypass().get_youtube_strategies())}")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=not IS_RAILWAY,
        threaded=True
    )