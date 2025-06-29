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
import unicodedata
from datetime import datetime
import requests
from urllib.parse import quote, unquote, urlparse, parse_qs
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

def turkce_karakterleri_temizle(metin):
    """Türkçe karakterleri İngilizce karşılıklarıyla değiştirir"""
    if not metin:
        return "video"
    
    # Türkçe karakter haritası
    turkce_harfler = {
        'ı': 'i', 'İ': 'I', 'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U', 'ş': 's', 'Ş': 'S',
        'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C'
    }
    
    # Türkçe karakterleri değiştir
    for tr_harf, en_harf in turkce_harfler.items():
        metin = metin.replace(tr_harf, en_harf)
    
    # Regex hatasını düzelt: \s- yerine \w\s\-\. kullan
    metin = re.sub(r'[^\w\s\-\.]', '', metin)
    metin = re.sub(r'\s+', '_', metin.strip())
    
    return metin[:50]  # Maksimum 50 karakter

def guvenli_dosya_adi_olustur(baslik):
    """HTTP header'ında güvenli kullanılabilecek dosya adı oluşturur"""
    if not baslik:
        return "video"
    
    # Önce Türkçe karakterleri temizle
    temiz_baslik = turkce_karakterleri_temizle(baslik)
    
    # ASCII'ye çevir ve özel karakterleri kaldır
    ascii_baslik = unicodedata.normalize('NFKD', temiz_baslik)
    ascii_baslik = ascii_baslik.encode('ascii', 'ignore').decode('ascii')
    
    # Sadece güvenli karakterleri bırak - regex hatasını düzelt
    guvenli_baslik = re.sub(r'[^\w\s\-\.]', '', ascii_baslik)
    guvenli_baslik = re.sub(r'\s+', '_', guvenli_baslik.strip())
    
    return guvenli_baslik[:40] if guvenli_baslik else "video"

def facebook_url_resolver(url):
    """Facebook share URL'lerini gerçek video URL'lerine çevirir"""
    try:
        # Facebook share URL'lerini resolve et
        if 'facebook.com/share' in url or 'fb.watch' in url:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # URL'yi takip et ve gerçek URL'yi bul
            response = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            final_url = response.url
            
            # Facebook video URL formatlarını kontrol et
            if 'facebook.com' in final_url and ('video' in final_url or 'watch' in final_url):
                return final_url
            
            # HTML içinde video URL'sini ara
            html_content = response.text
            import re
            
            # Farklı Facebook video URL pattern'larını ara
            patterns = [
                r'https://www\.facebook\.com/[^/]+/videos/\d+',
                r'https://www\.facebook\.com/watch/\?v=\d+',
                r'https://facebook\.com/[^/]+/videos/\d+',
                r'https://facebook\.com/watch/\?v=\d+',
                r'"videoId":"(\d+)"',
                r'"video_id":"(\d+)"'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html_content)
                if matches:
                    if 'videoId' in pattern or 'video_id' in pattern:
                        # Video ID bulundu, URL oluştur
                        video_id = matches[0]
                        return f"https://www.facebook.com/watch/?v={video_id}"
                    else:
                        return matches[0]
            
            return final_url
        
        return url
        
    except Exception as e:
        logger.warning(f"Facebook URL resolve failed: {e}")
        return url
    """RFC 5987 standardına göre dosya adını kodlar (alternatif çözüm)"""
    if not baslik:
        return "filename=video.mp4"
    
    try:
        # UTF-8 olarak kodla
        encoded_baslik = quote(baslik.encode('utf-8'))
        return f"filename*=UTF-8''{encoded_baslik}.mp4"
    except:
        # Hata durumunda güvenli versiyonu kullan
        guvenli_ad = guvenli_dosya_adi_olustur(baslik)
        return f"filename={guvenli_ad}.mp4"

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
            if 'youtube' in url.lower() or 'youtu.be' in url.lower():
                return self._youtube_quick(url, quality, temp_dir)
            elif 'instagram.com' in url.lower():
                return self._instagram_quick(url, quality, temp_dir)
            elif 'facebook.com' in url.lower() or 'fb.watch' in url.lower():
                return self._facebook_quick(url, quality, temp_dir)
            elif 'tiktok.com' in url.lower():
                return self._tiktok_quick(url, quality, temp_dir)
            else:
                return self._other_quick(url, quality, temp_dir)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _youtube_quick(self, url, quality, temp_dir):
        """Hızlı YouTube indirme - bot koruması bypass"""
        strategies = [
            {
                'name': 'Anonymous Mobile',
                'quality': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                'args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['ios', 'mweb'],
                        'player_skip': ['configs'],
                        'innertube_host': 'studio.youtube.com'
                    }
                }
            },
            {
                'name': 'Embed Bypass',
                'quality': 'best[height<=480][ext=mp4]/worst[ext=mp4]/best',
                'agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'args': {
                    'youtube': {
                        'skip': ['dash'],
                        'player_client': ['embed', 'android'],
                        'player_skip': ['webpage']
                    }
                }
            },
            {
                'name': 'TV Client',
                'quality': 'best[height<=720]/best',
                'agent': 'Mozilla/5.0 (SMART-TV; LINUX; Tizen 2.4.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/2.4.0 TV Safari/538.1',
                'args': {
                    'youtube': {
                        'player_client': ['tv', 'tvhtml5'],
                        'skip': ['dash']
                    }
                }
            },
            {
                'name': 'Age Gate Bypass',
                'quality': 'worst[ext=mp4]/worst',
                'agent': 'Mozilla/5.0 (Linux; Android 11; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.104 Mobile Safari/537.36',
                'args': {
                    'youtube': {
                        'player_client': ['android_testsuite', 'android_embedded'],
                        'skip': ['dash', 'hls']
                    }
                }
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
                    'extractor_retries': 1,
                    'fragment_retries': 1,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'age_limit': 18,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                    'no_check_certificate': True
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Quick info extraction with timeout
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    # Orijinal başlığı kaydet
                    orijinal_baslik = info.get('title', 'video')
                    # Güvenli dosya adı oluştur
                    temiz_baslik = self._clean_title(orijinal_baslik)
                    
                    # Update output path
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{temiz_baslik}.%(ext)s')
                    
                    # Download
                    ydl.download([url])
                    
                    # Check file
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            # Hem orijinal hem de temiz başlığı döndür
                            return file_path, orijinal_baslik, temiz_baslik
                            
            except Exception as e:
                self.logger.warning(f"Strategy {strategy['name']} failed: {e}")
                continue
                
            def _instagram_quick(self, url, quality, temp_dir):
        """Instagram video indirme"""
        strategies = [
            {
                'name': 'Instagram Mobile',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'quality': 'best[ext=mp4]/best'
            },
            {
                'name': 'Instagram Desktop',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'quality': 'best/worst'
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
                    'extractor_retries': 2,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    orijinal_baslik = info.get('title', 'instagram_video')
                    temiz_baslik = self._clean_title(orijinal_baslik)
                    
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{temiz_baslik}.%(ext)s')
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, orijinal_baslik, temiz_baslik
                            
            except Exception as e:
                self.logger.warning(f"Instagram strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All Instagram strategies failed")

    def _facebook_quick(self, url, quality, temp_dir):
        """Facebook video indirme - gelişmiş URL çözümleme"""
        
        # Önce URL'yi resolve et
        resolved_url = facebook_url_resolver(url)
        self.logger.info(f"Original URL: {url}")
        self.logger.info(f"Resolved URL: {resolved_url}")
        
        strategies = [
            {
                'name': 'Facebook Direct',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'quality': 'best[ext=mp4]/best',
                'url': resolved_url
            },
            {
                'name': 'Facebook Mobile',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'quality': 'best[ext=mp4]/best',
                'url': resolved_url
            },
            {
                'name': 'Facebook Original',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'quality': 'best/worst',
                'url': url  # Orijinal URL'yi de dene
            },
            {
                'name': 'Facebook Generic',
                'agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
                'quality': 'worst[ext=mp4]/worst',
                'url': resolved_url
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
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Cache-Control': 'no-cache'
                    },
                    'socket_timeout': 30,
                    'extractor_retries': 3,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True,
                    'ignore_errors': False,
                    'extract_flat': False
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Önce info extraction dene
                    info = ydl.extract_info(strategy['url'], download=False)
                    if not info:
                        self.logger.warning(f"No info extracted for {strategy['name']}")
                        continue
                        
                    orijinal_baslik = info.get('title', 'facebook_video')
                    temiz_baslik = self._clean_title(orijinal_baslik)
                    
                    # Download
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{temiz_baslik}.%(ext)s')
                    ydl.download([strategy['url']])
                    
                    # Check file
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            self.logger.info(f"Facebook download successful: {file_path}")
                            return file_path, orijinal_baslik, temiz_baslik
                            
            except Exception as e:
                self.logger.warning(f"Facebook strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All Facebook strategies failed")

    def _tiktok_quick(self, url, quality, temp_dir):
        """TikTok video indirme"""
        strategies = [
            {
                'name': 'TikTok Mobile',
                'agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
                'quality': 'best[ext=mp4]/best'
            },
            {
                'name': 'TikTok Desktop',
                'agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'quality': 'best/worst'
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
                        'Upgrade-Insecure-Requests': '1'
                    },
                    'socket_timeout': 30,
                    'extractor_retries': 2,
                    'max_filesize': MAX_CONTENT_LENGTH,
                    'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')},
                    'no_check_certificate': True
                }
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    orijinal_baslik = info.get('title', 'tiktok_video')
                    temiz_baslik = self._clean_title(orijinal_baslik)
                    
                    opts['outtmpl']['default'] = os.path.join(temp_dir, f'{temiz_baslik}.%(ext)s')
                    ydl.download([url])
                    
                    files = os.listdir(temp_dir)
                    if files:
                        file_path = os.path.join(temp_dir, files[0])
                        if os.path.getsize(file_path) > 1024:
                            return file_path, orijinal_baslik, temiz_baslik
                            
            except Exception as e:
                self.logger.warning(f"TikTok strategy {strategy['name']} failed: {e}")
                continue
                
        raise Exception("All TikTok strategies failed")

    def _other_quick(self, url, quality, temp_dir):
        """Diğer platformlar için hızlı indirme - yüksek kalite"""
        opts = {
            'format': quality or 'best[height<=1080]/best[height<=720]/best',
            'quiet': True,
            'no_warnings': True,
            'http_headers': {'User-Agent': random.choice(USER_AGENTS)},
            'socket_timeout': 30,
            'extractor_retries': 3,
            'max_filesize': MAX_CONTENT_LENGTH,
            'outtmpl': {'default': os.path.join(temp_dir, '%(title)s.%(ext)s')}
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise Exception("Could not extract video info")
                
            orijinal_baslik = info.get('title', 'video')
            temiz_baslik = self._clean_title(orijinal_baslik)
            opts['outtmpl']['default'] = os.path.join(temp_dir, f'{temiz_baslik}.%(ext)s')
            
            ydl.download([url])
            
            files = os.listdir(temp_dir)
            if files:
                return os.path.join(temp_dir, files[0]), orijinal_baslik, temiz_baslik
                
        raise Exception("Download failed")

    def _clean_title(self, title):
        """Dosya sistemi için güvenli başlık oluştur"""
        return guvenli_dosya_adi_olustur(title)

# API Endpoints
@app.route('/')
def home():
    return jsonify({
        'service': 'ReelDrop API',
        'version': '2.9-multi-platform',
        'status': 'running',
        'max_download_time': f'{DOWNLOAD_TIMEOUT}s',
        'max_file_size': f'{MAX_CONTENT_LENGTH // (1024*1024)}MB',
        'features': ['Fast YouTube bypass', 'Timeout protection', 'Memory optimization', 'Multi-platform support', 'Instagram/Facebook/TikTok support']
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
        quality = data.get('quality', 'best[height<=1080]/best[height<=720]/best')
        
        logger.info(f"[{request_id}] Download started: {url}")
        
        # URL validation
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'Invalid URL', 'request_id': request_id}), 400
        
        # Download with timeout
        downloader = QuickDownloader()
        
        try:
            # Artık 3 değer dönüyor: file_path, orijinal_baslik, temiz_baslik
            download_result = downloader.download_with_timeout(url, quality, DOWNLOAD_TIMEOUT)
            
            if len(download_result) == 3:
                file_path, orijinal_baslik, temiz_baslik = download_result
            else:
                # Eski format uyumluluğu
                file_path, orijinal_baslik = download_result
                temiz_baslik = guvenli_dosya_adi_olustur(orijinal_baslik)
                
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
        
        logger.info(f"[{request_id}] Success: {orijinal_baslik} -> {temiz_baslik} ({file_size} bytes, {processing_time}s)")
        
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
        
        # Güvenli dosya adını header için kullan
        guvenli_dosya_adi = guvenli_dosya_adi_olustur(orijinal_baslik)
        
        return Response(
            stream_with_context(generate()),
            content_type='video/mp4',
            headers={
                'Content-Length': str(file_size),
                'Content-Disposition': f'attachment; filename="{guvenli_dosya_adi}.mp4"',
                'Cache-Control': 'no-cache',
                'X-Processing-Time': str(processing_time),
                'X-Request-ID': request_id,
                'X-Original-Title': guvenli_dosya_adi_olustur(orijinal_baslik)  # Güvenli versiyon
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
    logger.info(f"Starting ReelDrop API v2.7 on port {PORT}")
    logger.info(f"Download timeout: {DOWNLOAD_TIMEOUT}s")
    logger.info(f"Max file size: {MAX_CONTENT_LENGTH // (1024*1024)}MB")
    logger.info("Turkish character support: ENABLED")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )