#!/usr/bin/env python3
"""听风的蚕（YouTube @zhuweiyi）专用采集管道。

★★ 当前状态：【已搁置，不接入日常 cron】（Chao 2026-09-07 拍板）
   「像这种没有字幕的 YouTube 暂时不跑，尽量从其他文字渠道先拿信息，
     不然太费时间」
   本脚本保留为【已探明的结论存档】，不是待办。要跑必须显式加 --force。

★ 探明的事实（2026-09-07 实测，别再重复试）：
   · 频道列表：无 cookies 可拿 ✓（15 条战争分析视频，已剔除小说连载）
   · 字幕通道：--list-subs 明确返回 no subtitles —— 该频道【无字幕轨】✗
   · 音频通道：HTTP Error 403 ✗
     与配方 youtube-403-unlock-recipe.md §A 表格一致：
     cookies + Deno + --remote-components ejs:github 三件套缺一即 403。
     本机 Deno ✓ / yt_dlp ✓ / .secrets/ 空 ✗ —— 缺的就是 cookies，
     而 cookies 只能由 Chao 从浏览器导出，agent 无法自行生成。
   · 文字渠道：只有第三方整理稿（知乎「春去秋来」的节目文字稿）。
     内容属实、数据具体，但【非本人发布】=转述，按归属铁律不入库。
     Chao 决定：「不收，他留在监测中区」。

★ 为什么当初要单独一条管道（Chao 追问「怎么会一个文字都没抓到」）：
  他是名册里【唯一的纯 YouTube 口播博主】，没有任何自有文章站点。
  常规抓取器走搜索引擎 + site: 定向，对他全部失效：
    · _own_sites() 把 youtube.com 当通用平台排除（这条排除本身是对的，
      否则 site:youtube.com 等于搜全站，会把任何人的视频都算成他的）
    · 中文名「聽風的蠶」是繁体，简体搜索命中差
  但 61/62 人都有文字源 —— 这是孤例，为 1 人建音频管道不划算。

用法（保留供日后 cookies 到位时使用）：
  python3 scripts/fetch_youtube_kol.py --list             # 列频道近期视频
  python3 scripts/fetch_youtube_kol.py --probe <VIDEO_ID> # 探测可达性
  python3 scripts/fetch_youtube_kol.py --run --force      # 全流程（需 cookies）
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SCRATCH = os.path.join(ROOT, "scratch")
YT_DIR = os.path.join(SCRATCH, "yt")
TR_DIR = os.path.join(SCRATCH, "transcripts")
COOKIES = os.path.join(ROOT, ".secrets", "yt_cookies.txt")

CHANNEL = "https://www.youtube.com/@zhuweiyi/videos"
KOL_NAME = 'Zhu Weiyi ("Ting Feng De Can")'

# Deno 路径注入进程环境，别依赖调用方 shell（配方 §D）
_DENO = os.path.expanduser("~/.deno/bin")
if os.path.isdir(_DENO) and _DENO not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _DENO + ":" + os.environ["PATH"]

# ★ 只要战争分析类，排除小说连载／娱乐
#   「非洲风云 我给叛军当军师」是他的虚构连载小说，不是分析言论——
#   混进来会污染言论库（这类必须在入口就挡，别指望下游 LLM 判）
FICTION = re.compile(r"我给叛军当军师|第[零一二三四五六七八九十百\d]+章|小说|连载")
WAR_HINT = re.compile(
    r"俄|乌|伊朗|以色列|美军|中东|台海|南海|导弹|无人机|核|战争|战局|军事|"
    r"打击|空袭|防空|航母|北约|停火|谈判|封锁|制裁")


def _yt(args, timeout=300):
    cmd = [sys.executable, "-m", "yt_dlp"] + args
    if os.path.exists(COOKIES):
        cmd = cmd[:3] + ["--cookies", COOKIES] + cmd[3:]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def list_videos(limit=40):
    rc, out, err = _yt([
        "--flat-playlist", "--playlist-end", str(limit),
        "--print", "%(id)s|%(title)s", CHANNEL], timeout=180)
    vids = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        vid, title = line.split("|", 1)
        vid, title = vid.strip(), title.strip()
        if not re.fullmatch(r"[\w-]{11}", vid):
            continue
        if FICTION.search(title):
            continue                      # 小说连载，不是言论
        if not WAR_HINT.search(title):
            continue                      # 与战争分析无关
        vids.append({"id": vid, "title": title})
    return vids


def probe(vid):
    """返回 (通道, 详情)。通道 ∈ subs / audio / blocked。"""
    url = f"https://www.youtube.com/watch?v={vid}"
    rc, out, err = _yt(["--list-subs", "--skip-download", url], timeout=180)
    blob = out + err
    has_sub = not re.search(r"has no subtitles", blob) or \
        not re.search(r"has no automatic captions", blob)
    if "has no subtitles" not in blob:
        return "subs", "有字幕轨"
    # 无字幕 → 试音频（配方 §G 第2步）
    rc, out, err = _yt([
        "--remote-components", "ejs:github",
        "-x", "--audio-format", "mp3", "--audio-quality", "5",
        "-o", os.path.join(YT_DIR, "%(id)s.%(ext)s"), url], timeout=600)
    blob = out + err
    if rc == 0 and os.path.exists(os.path.join(YT_DIR, f"{vid}.mp3")):
        return "audio", "音频下载成功"
    if "403" in blob:
        cue = ("缺 cookies（三件套之首）" if not os.path.exists(COOKIES)
               else "cookies 可能已失效")
        return "blocked", f"音频 403 —— {cue}"
    return "blocked", (blob.strip().splitlines() or ["未知失败"])[-1][:120]


def transcribe(mp3):
    """faster-whisper 本地转写（配方 §F：不走任何网关，纯本机推理）。"""
    from faster_whisper import WhisperModel
    m = WhisperModel("small", device="cpu", compute_type="int8",
                     download_root=os.path.join(ROOT, ".cache", "whisper"))
    segs, _ = m.transcribe(mp3, language="zh", beam_size=1, vad_filter=True)
    return " ".join(s.text.strip() for s in segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--probe", metavar="VIDEO_ID")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Chao 2026-09-07 已搁置该通道，--run 必须配 --force")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()

    if a.run and not a.force:
        print("✗ 该通道已搁置（Chao 2026-09-07：「没有字幕的 YouTube 暂时不跑」）。")
        print("  探明结论：该频道无字幕轨 + 音频缺 cookies 恒 403；")
        print("  第三方文字稿属转述，按归属铁律不入库。")
        print("  他停在 dashboard 的「监测中·待验证」区，这是如实标注。")
        print("  确要跑请显式加 --force。")
        sys.exit(3)

    os.makedirs(YT_DIR, exist_ok=True)
    os.makedirs(TR_DIR, exist_ok=True)

    if a.list:
        vs = list_videos(40)
        print(f"战争分析类视频 {len(vs)} 条（已剔除小说连载）：")
        for v in vs:
            print(f"  {v['id']}  {v['title']}")
        return

    if a.probe:
        ch, why = probe(a.probe)
        print(f"{a.probe} → 通道={ch}  {why}")
        return

    if a.run:
        if not os.path.exists(COOKIES):
            print("✗ 缺 .secrets/yt_cookies.txt —— 音频通道必然 403。")
            print("  配方 youtube-403-unlock-recipe.md §A 已实测：")
            print("  cookies / Deno / --remote-components ejs:github 三件套")
            print("  缺任一件都回落 403。字幕通道可无 cookies，但该频道无字幕轨。")
            sys.exit(2)
        vs = list_videos(40)[:a.limit]
        out = []
        for i, v in enumerate(vs, 1):
            ch, why = probe(v["id"])
            print(f"[{i}/{len(vs)}] {v['title'][:34]} → {ch} {why}")
            if ch != "audio":
                continue
            mp3 = os.path.join(YT_DIR, f"{v['id']}.mp3")
            txt = transcribe(mp3)
            p = os.path.join(TR_DIR, f"{v['id']}_zhuweiyi.txt")
            open(p, "w", encoding="utf-8").write(txt)
            out.append({
                "kol": KOL_NAME, "theater": ["俄乌"],
                "source_url": f"https://www.youtube.com/watch?v={v['id']}",
                "title": v["title"], "transcript_path": p,
                "chars": len(txt), "status": "ok",
                "collected_on": date.today().isoformat(),
            })
        p = os.path.join(DATA, f"youtube_zhuweiyi_{date.today().isoformat()}.json")
        json.dump(out, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n转写 {len(out)} 条 → {p}")


if __name__ == "__main__":
    main()
