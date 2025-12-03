import os
import tempfile
import io
import logging # 1. 新增日志模块，方便在 Render 看报错
from flask import Flask, render_template, request, send_file, jsonify, make_response, send_from_directory
from yt_dlp import YoutubeDL, DownloadError

app = Flask(__name__)

# 设置日志，这样如果报错，Render 的 Logs 里能看到具体原因
logging.basicConfig(level=logging.DEBUG)

# =======================================================
# 1. 解决 favicon.ico 404 问题
# =======================================================
@app.route('/favicon.ico')
def favicon():
    # 返回一个空响应，消除浏览器的 404 错误
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

# =======================================================
# 主路由：处理 GET (显示表单) 和 POST (下载音频)
# =======================================================
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')
        
        if not youtube_url:
            return render_template('index.html', error="请输入一个有效的 YouTube 链接。")

        mem_file = None
        final_filename = "audio.mp3"

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320', 
                    }],
                    'quiet': True,
                    'noprogress': True,
                    # 增加 User-Agent 伪装，防止被 YouTube 拒绝
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                }

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    video_title = info.get('title', 'audio_file')
                    
                    downloaded_file_path = os.path.join(temp_dir, f"{video_title}.mp3")
                    
                    if not os.path.exists(downloaded_file_path):
                        all_files = os.listdir(temp_dir)
                        mp3_files = [f for f in all_files if f.endswith('.mp3')]
                        if mp3_files:
                             downloaded_file_path = os.path.join(temp_dir, mp3_files[0])
                             video_title = os.path.splitext(mp3_files[0])[0]
                        else:
                            raise FileNotFoundError("无法找到转换后的 MP3 文件。")

                    with open(downloaded_file_path, 'rb') as f:
                        mem_file = io.BytesIO(f.read())
                    
                    final_filename = f"{video_title}.mp3"

            mem_file.seek(0)

            response = make_response(send_file(
                mem_file,
                as_attachment=True,
                download_name=final_filename,
                mimetype='audio/mpeg'
            ))

            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

            return response

        except Exception as e:
            app.logger.error(f"Download Error: {str(e)}") # 记录错误到日志
            return render_template('index.html', error=f"发生错误: {str(e)}")

    return render_template('index.html')

# =======================================================
# 异步路由：获取视频信息 (修复了 500 错误)
# =======================================================
@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    youtube_url = data.get('youtube_url')

    if not youtube_url:
        return jsonify({"success": False, "message": "未提供链接"}), 400

    # 2. 关键修复：移除了 'force_generic_extractor'
    # 并添加了 ignoreerrors 以防止单个视频流错误导致整个请求崩溃
    ydl_opts = {
        'quiet': True, 
        'skip_download': True,
        'ignoreerrors': True, 
        'no_warnings': True,
        # 增加 User-Agent 伪装
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            # 尝试提取信息
            info = ydl.extract_info(youtube_url, download=False)
            
            if not info:
                return jsonify({"success": False, "message": "无法获取视频信息"}), 500

            thumbnail_url = None
            if info.get('thumbnails'):
                # 获取最后一张缩略图（通常是最高清的）
                thumbnail_url = info['thumbnails'][-1]['url']
            
            return jsonify({
                "success": True,
                "title": info.get('title', '视频标题'),
                "thumbnail_url": thumbnail_url
            })
    except Exception as e:
        app.logger.error(f"Fetch Info Error: {str(e)}") # 这样你能在 Render Logs 看到具体报错
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)