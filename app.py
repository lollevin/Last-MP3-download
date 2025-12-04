import os
import tempfile
import io
import logging
import shutil
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

ORIGINAL_COOKIE_PATH = '/etc/secrets/cookies.txt'
TEMP_COOKIE_PATH = '/tmp/cookies.txt'

@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

@app.route('/logo.png')
def logo():
    return app.response_class(response=b'', status=200, mimetype='image/png')

def setup_cookies():
    # 尝试复制 Cookie，如果失败也不要报错，继续尝试无 Cookie 访问
    if os.path.exists(ORIGINAL_COOKIE_PATH):
        try:
            if os.path.exists(TEMP_COOKIE_PATH):
                os.remove(TEMP_COOKIE_PATH)
            shutil.copy(ORIGINAL_COOKIE_PATH, TEMP_COOKIE_PATH)
            return TEMP_COOKIE_PATH
        except Exception:
            pass
    return None

def get_ydl_opts(is_download=False):
    cookie_file = setup_cookies()
    
    opts = {
        'quiet': True,
        'noprogress': True,
        'cookiefile': cookie_file,
        'socket_timeout': 15,
        
        # 【关键修改】使用 TV/Android 客户端策略
        # TV 客户端通常 API 限制最少，最不容易报 429
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'skip': ['web'], # 强制跳过 web 客户端，因为 web 最容易被封
            }
        },
        # 移除固定的 User-Agent，让 yt-dlp 根据客户端自动选择
    }

    if is_download:
        opts.update({
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        opts.update({
            'skip_download': True,
            'ignoreerrors': True, # 允许忽略错误，防止直接抛出异常
        })
    
    return opts

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('youtube_url')
        if not url: return render_template('index.html', error="请输入链接")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ydl_opts = get_ydl_opts(is_download=True)
                ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    # 【防崩溃检查】
                    if not info:
                        raise Exception("YouTube 拒绝了访问 (429)，请稍后再试")

                    title = info.get('title', 'audio')
                    
                    target = None
                    for f in os.listdir(temp_dir):
                        if f.endswith('.mp3'):
                            target = os.path.join(temp_dir, f)
                            break
                    
                    if not target: raise Exception("文件转换失败")

                    with open(target, 'rb') as f:
                        mem = io.BytesIO(f.read())
                    
                    final_name = f"{title}.mp3"

            mem.seek(0)
            resp = make_response(send_file(mem, as_attachment=True, download_name=final_name, mimetype='audio/mpeg'))
            return resp

        except Exception as e:
            app.logger.error(f"DL Error: {e}")
            return render_template('index.html', error="下载失败：服务器 IP 暂时受限，请更新 Cookie 或稍后再试。")

    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    url = data.get('youtube_url')
    if not url: return jsonify({"success": False}), 400

    try:
        ydl_opts = get_ydl_opts(is_download=False)
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # 【关键修复】这里之前报错 NoneType
            # 现在如果 info 是 None，我们手动处理，不让它崩溃
            if info is None:
                app.logger.warning("YouTube returned None (429 Blocked)")
                return jsonify({"success": False, "message": "IP暂时受限"}), 500
            
            thumb = info.get('thumbnails', [{}])[-1].get('url')
            return jsonify({"success": True, "title": info.get('title'), "thumbnail_url": thumb})
            
    except Exception as e:
        app.logger.error(f"Info Error: {e}")
        return jsonify({"success": False, "message": "获取信息失败"}), 500

if __name__ == '__main__':
    app.run(debug=True)