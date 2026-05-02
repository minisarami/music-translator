import os
import json
import base64
import re
import streamlit as st
import yt_dlp
from openai import OpenAI
from google import genai
import streamlit.components.v1 as components

# --- 1. 基本設定（APIキーはStreamlitのシークレット機能で安全に読み込む） ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# クラウドサーバー上の保存先（同じフォルダ内）
SAVE_DIR = "temp_data"
BG_IMAGE_PATH = "artist.png"

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

client_oa = OpenAI(api_key=OPENAI_API_KEY)
client_ge = genai.Client(api_key=GEMINI_API_KEY)

# --- 2. ユーティリティ ---
def get_video_info(url):
    ydl_opts = {'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get('title', 'Unknown Title'), info.get('id')

def get_video_id(url):
    pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_bg_style(file_path):
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            data = f.read()
        return f'url("data:image/png;base64,{base64.b64encode(data).decode()}")'
    return 'url("https://images.unsplash.com/photo-1493225255756-d9584f8606e9?q=80&w=2000")'

# --- 3. デザイン設定 ---
st.set_page_config(page_title="Music Translation Port", layout="wide")
st.markdown(f"""
    <style>
    .stApp {{
        background: linear-gradient(rgba(255,255,255,0.75), rgba(255,255,255,0.75)), {get_bg_style(BG_IMAGE_PATH)};
        background-size: cover; background-position: center; background-attachment: fixed;
    }}
    .main .block-container {{ padding-top: 1.5rem; }}
    iframe {{ border-radius: 12px; }}
    </style>
    """, unsafe_allow_html=True)

st.title("✨ Music Translation Port")

# --- 4. 履歴管理 ---
history_file = os.path.join(SAVE_DIR, "history.json")
try:
    history = json.load(open(history_file, "r")) if os.path.exists(history_file) else {}
except json.JSONDecodeError:
    history = {}

def save_history():
    with open(history_file, "w") as f: json.dump(history, f, indent=4)

# --- 5. メイン処理 ---
url = st.text_input("YouTube URL", placeholder="URLを貼ってください")

if st.button("日本語の字幕をつくる ✨"):
    vid = get_video_id(url)
    if vid:
        if vid in history:
            st.info("翻訳済みです！")
        else:
            with st.status("翻訳中..."):
                try:
                    title, _ = get_video_info(url)
                    ydl_opts = {'format': 'bestaudio/best', 'outtmpl': f'{SAVE_DIR}/{vid}.%(ext)s'}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
                    
                    audio_path = f"{SAVE_DIR}/{vid}.webm"
                    if not os.path.exists(audio_path): audio_path = f"{SAVE_DIR}/{vid}.m4a"
                    
                    with open(audio_path, "rb") as f:
                        transcript = client_oa.audio.transcriptions.create(model="whisper-1", file=f, response_format="srt")
                    
                    response = client_ge.models.generate_content(
                        model="gemini-2.5-flash-lite", 
                        contents=f"以下のSRT形式の歌詞を日本語に翻訳してください。必ず【1行目に原文】、【2行目に日本語訳】というセットを維持し、タイムスタンプは消さないでください。挨拶や余計な説明は一切不要です。\n\n{transcript}"
                    )
                    history[vid] = {"title": title, "lyrics": response.text}
                    save_history()
                    st.rerun()
                except Exception as e:
                    st.error(f"エラー: {e}")

# --- 6. 履歴・表示（3:1 カラムレイアウト） ---
st.markdown("---")
for vid, data in reversed(list(history.items())):
    col_main, col_del = st.columns([0.96, 0.04])
    with col_main:
        with st.expander(f"🎵 {data['title']}", expanded=True):
            html_code = fr"""
            <div style="display: flex; flex-direction: row; gap: 15px; width: 100%; height: 420px; align-items: flex-start;">
                <div style="flex: 3; height: 100%;">
                    <iframe id="player" width="100%" height="100%" src="https://www.youtube.com/embed/{vid}?enablejsapi=1" frameborder="0" allowfullscreen></iframe>
                </div>
                <div style="flex: 1; height: 100%; display: flex; flex-direction: column; min-width: 200px;">
                    <div style="text-align: right; margin-bottom: 5px;">
                        <label style="color: #444; background: rgba(255,255,255,0.9); padding: 2px 8px; border-radius: 10px; font-size: 10px; cursor: pointer; border: 1px solid #ddd;">
                            <input type="checkbox" id="auto-scroll-sync" checked> 自動追従
                        </label>
                    </div>
                    <div id="lyrics-container" style="background: rgba(15,15,15,0.95); color: white; padding: 15px; border-radius: 10px; flex: 1; overflow-y: auto; font-family: sans-serif; text-align: center; border: 1px solid #333;">
                        <div id="lyrics-content" style="padding: 160px 0;"></div>
                    </div>
                </div>
            </div>
            <script>
            const lyricsData = `{data['lyrics']}`;
            const container = document.getElementById('lyrics-container');
            const content = document.getElementById('lyrics-content');
            const syncToggle = document.getElementById('auto-scroll-sync');
            let lastLineIndex = -1;

            const lines = lyricsData.split('\n\n').map(block => {{
                const parts = block.split('\n');
                if(parts.length >= 3) {{
                    const timeMatch = parts[1].match(/(\d+):(\d+):(\d+),(\d+)/);
                    if(timeMatch) {{
                        const seconds = parseInt(timeMatch[1])*3600 + parseInt(timeMatch[2])*60 + parseInt(timeMatch[3]);
                        return {{ time: seconds, text: parts.slice(2).join('<br>') }};
                    }}
                }}
            }}).filter(x => x);

            lines.forEach((line, i) => {{
                const el = document.createElement('div');
                el.id = 'line-' + i;
                el.innerHTML = line.text;
                el.style.cssText = 'margin-bottom:35px; transition:0.4s; opacity:0.25; font-size:15px; line-height:1.6;';
                content.appendChild(el);
            }});

            var tag = document.createElement('script');
            tag.src = "https://www.youtube.com/iframe_api";
            var firstScriptTag = document.getElementsByTagName('script')[0];
            firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

            var player;
            function onYouTubeIframeAPIReady() {{
                player = new YT.Player('player', {{ 
                    events: {{ 'onStateChange': onPlayerStateChange }} 
                }});
            }}

            function onPlayerStateChange(event) {{
                if (event.data == YT.PlayerState.PLAYING) {{
                    setInterval(() => {{
                        if (!player || !player.getCurrentTime) return;
                        const cur = player.getCurrentTime();
                        let activeIndex = -1;
                        lines.forEach((line, i) => {{ if (cur >= line.time) activeIndex = i; }});

                        if (activeIndex !== -1 && activeIndex !== lastLineIndex) {{
                            Array.from(content.children).forEach(c => {{ c.style.opacity = '0.25'; c.style.color = 'white'; }});
                            const activeEl = document.getElementById('line-' + activeIndex);
                            if(activeEl) {{
                                activeEl.style.opacity = '1';
                                activeEl.style.color = '#FFD700';

                                if (syncToggle.checked) {{
                                    const targetPos = activeEl.offsetTop - content.offsetTop - (container.offsetHeight / 2) + (activeEl.offsetHeight / 2);
                                    container.scrollTo({{ top: targetPos, behavior: 'smooth' }});
                                }}
                                lastLineIndex = activeIndex;
                            }}
                        }}
                    }}, 500);
                }}
            }}
            </script>
            """
            components.html(html_code, height=450)
    with col_del:
        if st.button("🗑️", key=f"del_{vid}"):
            if vid in history:
                del history[vid]
                save_history()
                st.rerun()