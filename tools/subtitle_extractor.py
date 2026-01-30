import subprocess
import json
import os
import collections

class SubtitleExtractor:
    @staticmethod
    def get_media_info(filepath):
        """
        使用 ffprobe 获取媒体信息，解析音频和字幕流
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=index,codec_name,codec_type:stream_disposition=default,dub,original,forced,hearing_impaired:stream_tags=language,title",
            "-of", "json",
            filepath
        ]
        
        try:
            # 确保不弹出 CMD 窗口 (Windows)
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=startupinfo)
            if result.returncode != 0:
                print(f"FFprobe error: {result.stderr}")
                return None
                
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            
            info = {
                "audio_langs": [],
                "default_audio_lang": None,
                "subtitles": []
            }
            
            audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
            subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
            
            # 解析音频语言
            lang_counter = collections.Counter()
            for s in audio_streams:
                lang = s.get("tags", {}).get("language", "und")
                lang_counter[lang] += 1
                
                # Check disposition default
                disp = s.get("disposition", {})
                if disp.get("default") == 1:
                    # 如果有多个 default 音频，这里会取最后一个，通常第一个即可，暂定覆盖
                    if info["default_audio_lang"] is None:
                        info["default_audio_lang"] = lang

            info["audio_langs"] = lang_counter
            # 如果没有找到 default audio track，取出现最多的语言
            if info["default_audio_lang"] is None and lang_counter:
                info["default_audio_lang"] = lang_counter.most_common(1)[0][0]
                
            # 解析字幕流
            for s in subtitle_streams:
                disp = s.get("disposition", {})
                sub_info = {
                    "index": s.get("index"),
                    "codec_name": s.get("codec_name"),
                    "language": s.get("tags", {}).get("language", "und"),
                    "title": s.get("tags", {}).get("title", ""),
                    "default": disp.get("default", 0) == 1,
                    "forced": disp.get("forced", 0) == 1,
                    "hearing_impaired": disp.get("hearing_impaired", 0) == 1,
                    "dub": disp.get("dub", 0) == 1
                }
                info["subtitles"].append(sub_info)
                
            # Check for missing codec (MKV fallback)
            if filepath.lower().endswith('.mkv') and any(not s.get("codec_name") for s in info["subtitles"]):
                 SubtitleExtractor.enrich_with_mkvmerge(filepath, info)
                 info.setdefault("warnings", []).append("注意: 检测到 FFprobe 未识别的字幕编码，已调用 mkvmerge 补充信息。")

            return info
            
        except Exception as e:
            print(f"Error getting media info: {e}")
            return None

    @staticmethod
    def get_default_selection(info):
        """
        根据音频语言和 disposition 推荐默认选中的字幕
        """
        if not info or not info["subtitles"]:
            return []
            
        target_lang = info.get("default_audio_lang", "und")
        selected_indices = []
        
        # 策略：
        # 匹配音频语言
        # 排除 Forced, Hearing Impaired
        
        # 尝试寻找完全匹配项
        candidates = []
        for sub in info["subtitles"]:
            # 排除条件
            if sub["forced"]: continue
            if sub["hearing_impaired"]: continue
            
            candidates.append(sub)
            
        # 筛选同语言
        matches = [s for s in candidates if s["language"] == target_lang]
        
        if matches:
            # 如果有匹配语言的，全选？通常只需要选一个最好的。
            # 这里逻辑：默认选中匹配语言的第一个非 Forced 非 HI。
            # 用户需求：选择与原声 consistent 的。
            selected_indices.append(matches[0]["index"])
        else:
            # 如果没有匹配语言的，但有候选（非 Forced/HI），选第一个
            if candidates:
                selected_indices.append(candidates[0]["index"])
                
        return selected_indices

    @staticmethod
    def extract_subtitles(filepath, track_indices, output_dir=None):
        """
        提取指定的字幕流
        track_indices: list of subtitle stream indices (e.g. [2, 3])
        """
        if not track_indices:
            return False, "No tracks selected"
            
        if output_dir is None:
            output_dir = os.path.dirname(filepath)
            
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        # 重新获取 codec 信息以确定后缀
        # 为简单起见，这里假设调用者传递了足够信息，或者再次探查。
        # 为了高效，我们在 extraction 内部不再探测，而是根据常见规则。
        # 但我们需要知道 source codec 才能决定是否转码。
        # 稍微重构：调用逻辑应在 UI 层决定，或者由 get_media_info 传递回来。
        # 这里为了独立性，先再次快速探测 codec 比较安全，或者直接根据后缀映射。
        # FFmpeg map command: -map 0:idx output
        
        # 改进：extract_subtitles 应该接收包含 codec 信息的 list，不仅仅是 indices
        # 由于接口限制，我们在这里做个简单的 info lookup 可能比较慢。
        # 实际上，我们可以构建一个复杂的命令，ffmpeg 会根据输出文件名后缀自动转换。
        # 比如 .srt 后缀，inputs 只要是 text-based (mov_text, subrip, webvtt) 都能转。
        # ass -> srt 会丢失特效。
        
        # 我们需要 sub_info 来决定扩展名。
        # 假设我们无法获取 sub_info，我们只能全部提取为 .srt 或 .ass (更加通用)
        # 按照用户要求：
        # mov_text -> srt
        # mkv 原格式 (ass -> ass, srt -> srt, vtt -> srt)
        
        # 为了正确获取 codec，最好这里再调一次 get_media_info 或者让调用者传入 sub_info objects。
        # 我们修改接口设计，假定调用者传的是 sub_info 字典列表。
        pass # implemented in extract_subtitles_v2

    @staticmethod
    def enrich_with_mkvmerge(filepath, info):
        """
        Use mkvmerge -J to get track info and fill missing codec_name
        """
        try:
            cmd = ["mkvmerge", "-J", filepath]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=startupinfo)
            if result.returncode != 0:
                print(f"Mkvmerge failed with code {result.returncode}")
                return

            mkv_data = json.loads(result.stdout)
            tracks = mkv_data.get("tracks", [])
            
            # Map by ID (subtitles only)
            track_map = {t["id"]: t for t in tracks if t["type"] == "subtitles"}
            
            for sub in info["subtitles"]:
                idx = sub["index"]
                if idx in track_map:
                    mkv_track = track_map[idx]
                    # If codec_name is missing, or we prefer mkv info
                    if not sub.get("codec_name"):
                        sub["codec_name"] = mkv_track.get("codec", "unknown")
                        sub["use_mkvextract"] = True
                        if "properties" in mkv_track:
                             sub["codec_id_mkv"] = mkv_track["properties"].get("codec_id")
        except Exception as e:
            print(f"Error executing mkvmerge: {e}")

    @staticmethod
    def run_mkvextract(filepath, subs, output_dir):
        """
        Batch extract using mkvextract
        """
        yield f"正在使用 mkvextract 提取 {len(subs)} 个字幕轨道..."
        
        args = []
        processed_files = []
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        for sub in subs:
            idx = sub["index"]
            lang = sub.get("language", "und")
            codec = sub.get("codec_name", "").lower()
            
            ext = "srt" # fallback
            if "webvtt" in codec or "vtt" in codec:
                ext = "vtt"
            elif "subrip" in codec or "srt" in codec:
                ext = "srt"
            elif "ass" in codec or "ssa" in codec:
                ext = "ass"
            elif "pgs" in codec:
                ext = "sup"
            elif "vobsub" in codec:
                ext = "idx" 
            
            out_filename = f"{base_name}.{lang}.{idx}.{ext}"
            out_path = os.path.join(output_dir, out_filename)
            
            args.append(f"{idx}:{out_path}")
            processed_files.append(out_filename)
            
        cmd = ["mkvextract", "tracks", filepath] + args
        
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', startupinfo=startupinfo)
            if proc.returncode == 0:
                yield f"提取成功 (mkvextract): {output_dir}"
                for f in processed_files:
                    yield f" - {f}"
            else:
                yield f"Mkvextract error: {proc.stdout}"
        except Exception as e:
            yield f"运行 mkvextract 出错: {e}"

    @staticmethod
    def extract_subtitles_v2(filepath, selected_subs, output_dir=None):
        """
        selected_subs: list of subtitle dictionaries (from get_media_info)
        """
        if not selected_subs:
            yield "未选择任何轨道"
            return
            
        if output_dir is None:
            output_dir = os.path.dirname(filepath)
            
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        mkv_subs = []
        ffmpeg_subs = []
        
        for sub in selected_subs:
            # Use mkvextract if flagged or if codec is missing (though enrichment should have fixed it, maybe codec still unknown)
            if sub.get("use_mkvextract"):
                mkv_subs.append(sub)
            else:
                ffmpeg_subs.append(sub)
        
        # 1. mkvextract tasks
        if mkv_subs:
            yield from SubtitleExtractor.run_mkvextract(filepath, mkv_subs, output_dir)
            
        # 2. ffmpeg tasks
        if ffmpeg_subs:
            cmd = ["ffmpeg", "-i", filepath, "-y"]
            processed_files = []
            
            for sub in ffmpeg_subs:
                idx = sub["index"]
                lang = sub["language"]
                codec = sub.get("codec_name")
                
                # Determine extension
                ext = "srt"
                if codec:
                    codec_lower = codec.lower()
                    if codec_lower in ["ass", "ssa"]:
                        ext = "ass"
                    elif codec_lower in ["mov_text", "webvtt", "subrip"]:
                        ext = "srt"
                    elif "pgs" in codec_lower or "dvd" in codec_lower:
                        ext = "sup"
                
                out_filename = f"{base_name}.{lang}.{idx}.{ext}"
                out_path = os.path.join(output_dir, out_filename)
                
                cmd.extend(["-map", f"0:{idx}", out_path])
                processed_files.append(out_filename)
            
            try:
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                yield f"正在提取 {len(ffmpeg_subs)} 个字幕轨道 (FFmpeg)..."
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', startupinfo=startupinfo)
                
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    # yield line.strip()
                    pass
                    
                proc.wait()
                
                if proc.returncode == 0:
                    yield f"提取成功 (FFmpeg)，已输出到: {output_dir}"
                    for f in processed_files:
                        yield f" - {f}"
                else:
                    yield "FFmpeg 提取过程中发生错误"
                    
            except Exception as e:
                yield f"运行 FFmpeg 出错: {e}"

if __name__ == "__main__":
    # Test
    pass
