import os
import tempfile
import io
from flask import Flask, render_template, request, send_file, jsonify, make_response # 1. 新增导入 make_response
from yt_dlp import YoutubeDL, DownloadError

app = Flask(__name__)

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
                # 320kbps 高音质配置
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320', # 确保是最高音质
                    }],
                    'quiet': True,
                    'noprogress': True,
                }

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    video_title = info.get('title', 'audio_file')
                    
                    # 寻找 MP3 文件
                    downloaded_file_path = os.path.join(temp_dir, f"{video_title}.mp3")
                    
                    # 容错查找
                    if not os.path.exists(downloaded_file_path):
                        all_files = os.listdir(temp_dir)
                        mp3_files = [f for f in all_files if f.endswith('.mp3')]
                        if mp3_files:
                             downloaded_file_path = os.path.join(temp_dir, mp3_files[0])
                             video_title = os.path.splitext(mp3_files[0])[0]
                        else:
                            raise FileNotFoundError("无法找到转换后的 MP3 文件。")

                    # 读取到内存
                    with open(downloaded_file_path, 'rb') as f:
                        mem_file = io.BytesIO(f.read())
                    
                    final_filename = f"{video_title}.mp3"

            # 指针归位
            mem_file.seek(0)

            # =======================================================
            # 2. 关键修复：创建响应对象并强制禁止缓存
            # =======================================================
            response = make_response(send_file(
                mem_file,
                as_attachment=True,
                download_name=final_filename,
                mimetype='audio/mpeg'
            ))

            # 添加 HTTP 头，告诉浏览器“绝对不要缓存这个请求”
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

            return response

        except Exception as e:
            return render_template('index.html', error=f"发生错误: {str(e)}")

    return render_template('index.html')

# =======================================================
# 异步路由：获取视频信息
# =======================================================
@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    youtube_url = data.get('youtube_url')

    if not youtube_url:
        return jsonify({"success": False, "message": "未提供链接"}), 400

    ydl_opts = {
        'quiet': True, 
        'skip_download': True, 
        'force_generic_extractor': True
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            thumbnail_url = info['thumbnails'][-1]['url'] if info.get('thumbnails') else None
            return jsonify({
                "success": True,
                "title": info.get('title', '视频标题'),
                "thumbnail_url": thumbnail_url
            })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)