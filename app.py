#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import tempfile
import shutil
import random
import time
import sys
import re
import threading
import unicodedata
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp

# Logging - hem console hem file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Startup log
print("=" * 50)
print("ReelDrop API Starting...")
print("=" * 50)

app = Flask(__name__)
CORS(app)

# Railway settings
PORT = int(os.environ.get('PORT', 8000))
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
DOWNLOAD_TIMEOUT = 120  # 2 minutes

USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 12; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

class TimeoutError(Exception):
    pass

def clean_filename(title):
    """Dosya adını temizle"""
    if not title:
        return "video"
    
    # Türkçe karakterleri değiştir
    turkce_map = {
        'ı': 'i', 'İ': 'I', 'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U', 'ş': 's', 'Ş': 'S',
        'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C'
    }
    
    for tr_char, en_char in turkce_map.items():
        title = title.replace(tr_char, en_char)
    
    # Sadece güvenli karakterler
    title = re.sub(r'[^\w\s\-\.]', '', title)
    title = re.sub(r'\s+', '_', title.strip())
    
    return title[:40] if title else "video"

class SimpleDownloader:
    def __init__(self):
        self.logger = logger
        self.result = None
        self.error = None

    def download_with_timeout(self, url, quality, timeout=DOWNLOAD_TIMEOUT):
        def download_worker():
            try:
                self.result = self._download(url, quality)
            except Exception as e:
                self.error = e

        thread = threading.Thread(target=download_worker)
        thread.daemon = True
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            raise TimeoutError(f"Download timeout after {timeout} seconds")
        
        if self.error:
            raise self.error
            
        return self.result

    def _download(self, url, quality):
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Platform tespiti
            if 'youtube' in url.lower() or 'youtu.be' in url.lower():
                return self._youtube_download(url, quality, temp_dir)
            elif 'instagram.com' in url.lower():
                return self._instagram_download(url, quality, temp_dir)
            elif 'facebook.com' in url.lower() or 'fb.watch' in url.lower():
                return self._facebook_download(url, quality, temp_dir)
            elif 'tiktok.com' in url.lower() or 'vm.tiktok.com' in url.lower() or 'vt.tiktok.com' in url.lower():
                return self._tiktok_download(url, quality, temp_dir)
            elif 'twitter.com' in url.lower() or 'x.com' in url.lower() or 't.co' in url.lower():
                self.logger.info(f"Twitter/X platform detected: {url}")
                return self._twitter_download(url, quality, temp_dir)
            else:
                # Bilinmeyen platform için sırayla dene
                self.logger.info("Unknown platform, trying multiple extractors...")
                
                # Önce TikTok dene (kısa linkler olabilir)
                try:
                    self.logger.info("Unknown URL - Trying TikTok extractor...")
                    return self._tiktok_download(url, quality, temp_dir)
                except Exception as tiktok_error:
                    self.logger.warning(f"TikTok failed: {tiktok_error}")
                
                # Sonra Twitter dene (X.com olabilir)
                try:
                    self.logger.info("Unknown URL - Trying Twitter/X extractor...")
                    return self._twitter_download(url, quality, temp_dir)
                except Exception as twitter_error:
                    self.logger.warning(f"Twitter failed: {twitter_error}")
                
                # Son olarak generic
                self.logger.info("Unknown URL - Trying generic extractor...")
                return self._generic_download(url, quality, temp_dir)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _youtube_download(self, url, quality, temp_dir):
        strategies = [
            {
                'name': 'TV Client - Single Stream',
                'quality': 'best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (SMART-TV; LINUX; Tizen 2.4.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/2.4.0 TV Safari/538.1',
                'args': {'youtube': {'player_client': ['tv_html5', 'tv'], 'skip': ['dash']}}
            },
            {
                'name': 'Mobile - Merged Format',
                'quality': 'best[height<=720][ext=mp4][vcodec!=none][acodec!=none]/worst[ext=mp4]',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'args': {'youtube': {'player_client': ['ios', 'mweb'], 'skip': ['dash', 'hls']}}
            },
            {
                'name': 'Embed Bypass - Low Quality',
                'quality': 'worst[ext=mp4][vcodec!=none][acodec!=none]/worst[ext=mp4]/worst',
                'agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'args': {'youtube': {'player_client': ['embed', 'android_embedded'], 'skip': ['dash', 'hls']}}
            },
            {
                'name': 'Age Gate Bypass',
                'quality': 'worst[ext=mp4]/worst',
                'agent': 'Mozilla/5.0 (Linux; Android 11; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.104 Mobile Safari/537.36',
                'args': {'youtube': {'player_client': ['android_testsuite'], 'skip': ['dash', 'hls']}}
            },
            {
                'name': 'Generic Fallback',
                'quality': 'best/worst',
                'agent': USER_AGENTS[2],
                'args': {}
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"YouTube strategy: {strategy['name']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': strategy['agent'],
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Encoding': 'gzip, deflate',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    },
                    'extractor_args': strategy['args'],
                    'socket_timeout': 30,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'age_limit': 18,
                    'no_check_certificate': True,
                    # Video/Audio senkronizasyon için
                    'merge_output_format': 'mp4',
                    'prefer_free_formats': False,
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }]
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    title = clean_filename(info.get('title', 'video'))
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"Strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All YouTube strategies failed")

    def _instagram_download(self, url, quality, temp_dir):
        """Instagram video indirme"""
        self.logger.info("Instagram download started")
        
        strategies = [
            {
                'name': 'Instagram Mobile',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1'
            },
            {
                'name': 'Instagram Desktop',
                'quality': 'best/worst',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"Instagram strategy: {strategy['name']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': strategy['agent'],
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    },
                    'socket_timeout': 30,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    title = clean_filename(info.get('title', 'instagram_video'))
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"Instagram strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All Instagram strategies failed")

    def _facebook_download(self, url, quality, temp_dir):
        """Facebook video indirme"""
        self.logger.info("Facebook download started")
        
        strategies = [
            {
                'name': 'Facebook Mobile',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1'
            },
            {
                'name': 'Facebook Desktop',
                'quality': 'best/worst',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            {
                'name': 'Facebook Bot',
                'quality': 'worst[ext=mp4]/worst',
                'agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)'
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"Facebook strategy: {strategy['name']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': strategy['agent'],
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    },
                    'socket_timeout': 30,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True,
                    'ignore_errors': True
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    title = clean_filename(info.get('title', 'facebook_video'))
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"Facebook strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All Facebook strategies failed")

    def _tiktok_download(self, url, quality, temp_dir):
        """TikTok video indirme - gelişmiş"""
        self.logger.info(f"TikTok download started for: {url}")
        
        strategies = [
            {
                'name': 'TikTok Mobile',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'extra_opts': {}
            },
            {
                'name': 'TikTok API',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'extra_opts': {'extractor_args': {'tiktok': {'api_hostname': ['api.tiktokv.com']}}}
            },
            {
                'name': 'TikTok Desktop',
                'quality': 'best/worst',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'extra_opts': {}
            },
            {
                'name': 'TikTok Bot',
                'quality': 'worst[ext=mp4]/worst',
                'agent': 'TikTok 1.0.0 rv:1.0.0 (iPhone; iOS 15.0; en_US) Cronet',
                'extra_opts': {}
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"TikTok strategy: {strategy['name']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': strategy['agent'],
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Referer': 'https://www.tiktok.com/'
                    },
                    'socket_timeout': 30,
                    'extractor_retries': 3,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True,
                    'ignore_errors': False
                }
                
                # Ekstra seçenekleri birleştir
                opts.update(strategy['extra_opts'])
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        self.logger.warning(f"No info extracted for {strategy['name']}")
                        continue
                        
                    title = clean_filename(info.get('title', 'tiktok_video'))
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            self.logger.info(f"TikTok download successful: {file_path}")
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"TikTok strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All TikTok strategies failed")

    def _twitter_download(self, url, quality, temp_dir):
        """Twitter/X video indirme - gelişmiş ve güçlendirilmiş"""
        self.logger.info(f"Twitter download started for: {url}")
        
        # URL normalizasyonu
        if 'x.com' in url:
            # x.com'u twitter.com'a çevir
            normalized_url = url.replace('x.com', 'twitter.com')
            self.logger.info(f"Normalized URL: {normalized_url}")
        else:
            normalized_url = url
        
        strategies = [
            {
                'name': 'Twitter Syndication API',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'extra_opts': {
                    'extractor_args': {
                        'twitter': {
                            'api': ['syndication'],
                            'legacy_api': True
                        }
                    }
                },
                'url': normalized_url
            },
            {
                'name': 'Twitter GraphQL',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'extra_opts': {
                    'extractor_args': {
                        'twitter': {
                            'api': ['graphql'],
                            'guest_token': True
                        }
                    }
                },
                'url': normalized_url
            },
            {
                'name': 'X.com Direct',
                'quality': 'best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'extra_opts': {},
                'url': url  # Orijinal x.com URL'si
            },
            {
                'name': 'Twitter Mobile Web',
                'quality': 'best/worst',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'extra_opts': {},
                'url': normalized_url
            },
            {
                'name': 'Twitter Legacy Fallback',
                'quality': 'worst[ext=mp4]/worst',
                'agent': 'Twitterbot/1.0',
                'extra_opts': {
                    'extractor_args': {
                        'twitter': {
                            'legacy_api': True
                        }
                    }
                },
                'url': normalized_url
            }
        ]
        
        for strategy in strategies:
            try:
                self.logger.info(f"Twitter strategy: {strategy['name']} with URL: {strategy['url']}")
                
                opts = {
                    'format': strategy['quality'],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': strategy['agent'],
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Cache-Control': 'no-cache'
                    },
                    'socket_timeout': 45,  # Daha uzun timeout
                    'extractor_retries': 5,  # Daha fazla retry
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True,
                    'ignore_errors': False
                }
                
                # Ekstra seçenekleri birleştir
                opts.update(strategy['extra_opts'])
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Önce info extraction
                    info = ydl.extract_info(strategy['url'], download=False)
                    if not info:
                        self.logger.warning(f"No info extracted for {strategy['name']}")
                        continue
                    
                    # Video var mı kontrol et
                    if not info.get('formats') and not info.get('url'):
                        self.logger.warning(f"No video formats found for {strategy['name']}")
                        continue
                        
                    title = clean_filename(info.get('title', 'twitter_video'))
                    self.logger.info(f"Video found: {title}")
                    
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
                    
                    # Download
                    ydl.download([strategy['url']])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            self.logger.info(f"Twitter download successful: {file_path}")
                            return file_path, title
                            
            except Exception as e:
                self.logger.warning(f"Twitter strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All Twitter strategies failed")

    def _generic_download(self, url, quality, temp_dir):
        """Diğer platformlar için basit indirme"""
        opts = {
            'format': quality or 'best',
            'quiet': True,
            'no_warnings': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)},
            'socket_timeout': 30,
            'max_filesize': MAX_CONTENT_LENGTH,
            'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')}
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise Exception("Could not extract video info")
                
            title = clean_filename(info.get('title', 'video'))
            opts['outtmpl']['default'] = os.path.join(temp_dir, f'{title}.%(ext)s')
            
            ydl.download([url])
            
            files = os.listdir(temp_dir)
            if files:
                return os.path.join(temp_dir, files[0]), title
                
        raise Exception("Download failed")

# Routes
@app.route('/')
def home():
    return jsonify({
        'service': 'ReelDrop API',
        'version': '3.8-clean-fix',
        'status': 'running',
        'supported_platforms': ['YouTube', 'Instagram', 'Facebook', 'TikTok', 'Twitter/X', 'Generic']
    })

@app.route('/health')
def health():
    return "OK", 200

@app.route('/download', methods=['POST'])
def download_video():
    start_time = time.time()
    request_id = f"req_{int(time.time())}"
    
    # Console'a da yazdır
    print(f"\n[{request_id}] NEW REQUEST RECEIVED")
    
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL required'}), 400
        
        url = data['url'].strip()
        quality = data.get('quality', 'best[height<=720]/best')
        
        logger.info(f"[{request_id}] Download started: {url}")
        logger.info(f"[{request_id}] URL length: {len(url)}")
        logger.info(f"[{request_id}] URL analysis: {url.lower()}")
        
        # URL debug için
        if 'x.com' in url.lower():
            logger.info(f"[{request_id}] X.com detected!")
        elif 'twitter.com' in url.lower():
            logger.info(f"[{request_id}] Twitter.com detected!")
        elif 'tiktok.com' in url.lower():
            logger.info(f"[{request_id}] TikTok.com detected!")
        else:
            logger.info(f"[{request_id}] Platform not detected, will try fallback")
        
        # URL validation - daha esnek
        if not (url.startswith(('http://', 'https://')) or url.startswith('www.')):
            logger.error(f"[{request_id}] Invalid URL format: {url}")
            return jsonify({'error': 'Invalid URL format', 'received_url': url}), 400
        
        downloader = SimpleDownloader()
        
        try:
            file_path, title = downloader.download_with_timeout(url, quality)
        except TimeoutError:
            return jsonify({'error': 'Download timeout'}), 408
        
        file_size = os.path.getsize(file_path)
        temp_dir = os.path.dirname(file_path)
        processing_time = round(time.time() - start_time, 2)
        
        logger.info(f"[{request_id}] Success: {title} ({file_size} bytes, {processing_time}s)")
        
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
                'Cache-Control': 'no-cache'
            }
        )
        
    except Exception as e:
        processing_time = round(time.time() - start_time, 2)
        logger.error(f"[{request_id}] Error: {str(e)} ({processing_time}s)")
        
        return jsonify({
            'error': 'Video indirilemedi',
            'processing_time': processing_time
        }), 500

if __name__ == '__main__':
    print(f"Starting ReelDrop API v3.5-debug-fix on port {PORT}")
    print("Supported platforms: YouTube, Instagram, Facebook, TikTok, Twitter/X")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    logger.info(f"Starting ReelDrop API v3.5-debug-fix on port {PORT}")
    logger.info("Supported platforms: YouTube, Instagram, Facebook, TikTok, Twitter/X")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=True,  # Debug mode açık
        threaded=True
    )