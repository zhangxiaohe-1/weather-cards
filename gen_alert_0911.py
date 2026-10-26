# -*- coding: utf-8 -*-
import urllib.request, urllib.parse, json, datetime, os, uuid, time, sys

# 让 base managed python 也能找到 venv 中的 Pillow（自动化用 base 解释器运行本脚本）
_VENV_SP = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "python", "envs", "default", "Lib", "site-packages")
if os.path.isdir(_VENV_SP) and _VENV_SP not in sys.path:
    sys.path.insert(0, _VENV_SP)

# 凭证：云端(GitHub Actions)经环境变量/Secrets 注入；硬编码值仅作本地运行兜底（待轮换后移除）
SCKEY = os.environ.get("SCKEY", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")   # GitHub 经典 PAT（repo 权限），已建公开图床仓库 zhangxiaohe-1/weather-cards
GH_REPO  = os.environ.get("GH_REPO", "zhangxiaohe-1/weather-cards")   # 公开仓库，存放预警卡片图片
GH_BRANCH = "main"

# ---- 自动化时间门控（单个 DAILY 任务，rrule 多时间点 19:40/23:40 触发；本门控作二次保险）----
# 目标小时：19（晚）/ 23（夜）。手动运行可加 --force 绕过；云端 workflow 设 FORCE=true 等效 --force。
_TARGET_HOURS = {19, 23}
if "--force" not in sys.argv and os.environ.get("FORCE", "") != "true":
    _now_h = datetime.datetime.now().hour
    if _now_h not in _TARGET_HOURS:
        print(f"SKIP: 当前小时 {_now_h} 非目标时段 {sorted(_TARGET_HOURS)}，定时任务空跑退出")
        sys.exit(0)

def push_serverchan(title, desp):
    _flag = ".alert_pushed_" + datetime.datetime.now().strftime('%Y-%m-%d')
    if os.path.exists(_flag):
        return '{"code":-2,"message":"DUPLICATE_SKIPPED_TODAY"}'
    """调用 Server酱 将消息推送到绑定的微信。返回接口响应文本。"""
    params = urllib.parse.urlencode({"title": title, "desp": desp})
    url = f"https://sctapi.ftqq.com/{SCKEY}.send?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            open(_flag, "w", encoding="utf-8").write("1");             return r.read().decode("utf-8")
    except Exception as e:
        return f"PUSH_ERR: {e}"

# ---------------- 图片卡片生成（Pillow） ----------------
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

def _font(size, bold=False):
    # 字体解析链：FONT_DIR 环境变量 → Windows 雅黑 → Linux Noto CJK（GitHub Actions 装 fonts-noto-cjk）→ 默认位图
    try:
        cands = []
        fd = os.environ.get("FONT_DIR", "")
        if fd:
            cands.append(os.path.join(fd, "msyhbd.ttc" if bold else "msyh.ttc"))
        cands += ["C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"]
        cands += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
        for p in cands:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def gen_pig_advice(triggered, max_span=0.0):
    """基于三轴差异化给出猪群环控建议：
       轴① 绝对低温（最低温等级）→ 保温/防冻
       轴② 连续天气变化温差（连续3天最高温跨度 span）→ 趋势性骤变应对
       轴③ 当日温差（昼夜 DTR = 最高-最低）→ 间歇通风/防冷风
    """
    all_lo = [r["lo"] for c in triggered for r in c["rows"] if "lo" in r]
    all_dtr = [r["dtr"] for c in triggered for r in c["rows"] if r.get("dtr")]
    tmin = min(all_lo) if all_lo else None
    max_dtr = max(all_dtr) if all_dtr else 0
    span = max_span if max_span else 0
    lines = []
    # —— 轴① 绝对低温等级 ——
    if tmin is not None:
        if tmin <= 0:
            lines.append(f"① 绝对低温·严寒(最低{tmin}℃)：仔猪保温箱32-34℃、保育/产房暖风地暖，水管防冻、防冷应激腹泻。")
        elif tmin <= 5:
            lines.append(f"① 绝对低温·低温(最低{tmin}℃)：夜间密闭门窗、开保温灯、垫料加厚、保育舍局部加温。")
        elif tmin <= 10:
            lines.append(f"① 绝对低温·偏凉(最低{tmin}℃)：关注夜间保温、产房维持恒温。")
        else:
            lines.append(f"① 绝对低温·温和(最低{tmin}℃)：维持常规环控即可。")
    # —— 轴② 连续天气变化温差（趋势性骤变）——
    if span >= 10:
        lines.append(f"② 连续变化·剧烈(3天最高温跨度{span:.0f}℃)：寒潮/强回暖，提前48h检修保温、平稳加温脱温、暂停转群与免疫。")
    elif span >= 6:
        lines.append(f"② 连续变化·明显(3天最高温跨度{span:.0f}℃)：关注升降温趋势，产房温度平稳过渡、防骤冷。")
    # —— 轴③ 当日温差（昼夜）——
    if max_dtr >= 15:
        lines.append(f"③ 当日温差·极大(昼夜{max_dtr:.0f}℃)：间歇通风、防冷风直吹、夜间加饲、巡栏盯呼吸道病。")
    elif max_dtr >= 10:
        lines.append(f"③ 当日温差·偏大(昼夜{max_dtr:.0f}℃)：间歇通风、防冷风直吹、巡栏盯采食量与喷嚏。")
    lines.append("提醒：人员洋葱式穿衣；猪场提前检修保温设备防应激。")
    return lines

def _wrap_text(text, max_chars=32):
    """按字符数换行，优先在中文标点处断开，避免超长行被截断。"""
    lines = []
    while text:
        if len(text) <= max_chars:
            lines.append(text)
            break
        sub = text[:max_chars]
        # 优先在标点处断开
        cut = -1
        for i in range(len(sub) - 1, -1, -1):
            if sub[i] in "，、；。,;. ":
                cut = i + 1
                break
        if cut <= 0:
            cut = max_chars
        lines.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return lines

def make_card(path, triggered, max_span=0.0):
    """triggered: list of {name, rows:[{date,weather,hi,lo}]}"""
    W = 640
    margin = 28
    f_title = _font(30, True); f_sub = _font(17)
    f_city = _font(24, True); f_note = _font(16)
    f_head = _font(16, True); f_row = _font(18); f_tip = _font(14)
    line_h = 36
    header_h = 92
    advice = gen_pig_advice(triggered, max_span)
    advice_lines = [ln for al in advice for ln in _wrap_text(al, max_chars=36)]
    h = margin + header_h + margin
    for c in triggered:
        h += 44 + 28 + 30 + line_h * len(c["rows"]) + 14
    h += 16 + len(advice_lines) * 22 + 32
    img = Image.new("RGB", (W, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, header_h], fill=(230, 74, 25))
    d.text((margin, 20), "气温波动预警", font=f_title, fill=(255, 255, 255))
    d.text((margin, 60), "海伦·梨树 监测 · 仅播报预警区域", font=f_sub, fill=(255, 238, 232))
    y = margin + header_h + 4
    for c in triggered:
        d.ellipse([margin, y + 8, margin + 16, y + 24], fill=(229, 57, 53))
        d.text((margin + 26, y), c["name"], font=f_city, fill=(33, 33, 33))
        y += 44
        d.text((margin + 4, y), "连续3天温差≥6℃ 或 单日最高最低温差>10℃，请注意气温波动", font=f_note, fill=(229, 57, 53))
        y += 28
        d.text((margin + 12, y), "日期", font=f_head, fill=(130, 130, 130))
        d.text((margin + 150, y), "天气", font=f_head, fill=(130, 130, 130))
        d.text((margin + 290, y), "最高", font=f_head, fill=(130, 130, 130))
        d.text((margin + 380, y), "最低", font=f_head, fill=(130, 130, 130))
        d.text((margin + 470, y), "温差", font=f_head, fill=(130, 130, 130))
        y += 30
        for r in c["rows"]:
            d.text((margin + 12, y), r["date"], font=f_row, fill=(33, 33, 33))
            d.text((margin + 150, y), r["weather"], font=f_row, fill=(33, 33, 33))
            d.text((margin + 290, y), f"{r['hi']}℃", font=f_row, fill=(211, 47, 47))
            d.text((margin + 380, y), f"{r['lo']}℃", font=f_row, fill=(21, 101, 192))
            if r.get("dtr"):
                d.text((margin + 470, y), f"{r['dtr']}℃", font=f_row, fill=(229, 57, 53))
            y += line_h
        y += 14
    # 底部：根据气温动态给出猪群环控建议（行宽与上方温差列右边缘对齐）
    for al in advice_lines:
        d.text((margin + 12, y), al, font=f_tip, fill=(90, 90, 90))
        y += 22
    img.save(path, "PNG")

def upload_github(path, token, repo, branch="main"):
    """上传到 GitHub 公开仓库（图床），返回公网直链（ghproxy.net 代理，国内可达）或 None。
    幂等：同一天重跑用相同文件名，更新已存在文件时必须带原文件 SHA，否则 GitHub 返回 422。"""
    import base64
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    api = f"https://api.github.com/repos/{repo}/contents/{fn}"
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
    }
    # 先查是否已有该文件，拿到 SHA（用于幂等更新）
    sha = None
    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
            sha = j.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sha = None  # 文件不存在，新建
        else:
            print("UPLOAD_HEAD_ERR:", e.code, e.read()[:200].decode("utf-8", "replace"))
            return None
    except Exception as e:
        print("UPLOAD_HEAD_ERR:", e)
        return None
    payload = {"message": f"weather alert card {fn}", "content": b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(api, data=json.dumps(payload).encode("utf-8"), method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode("utf-8"))
        # 用 ghproxy.net 代理直链（专为国内访问 GitHub 设计，避免 raw.githubusercontent.com 被墙）
        return f"https://ghproxy.net/https://raw.githubusercontent.com/{repo}/{branch}/{fn}"
    except urllib.error.HTTPError as e:
        print("UPLOAD_ERR:", e.code, e.read()[:200].decode("utf-8", "replace"))
    except Exception as e:
        print("UPLOAD_ERR:", e)
    return None

# ===================== 数据源说明（2026-10-26 改） =====================
# 抓取地点已改为：海伦市 + 梨树县。
# 当前 fetch 仍用 Open-Meteo（国外源）——它是唯一已确认可无人值守稳定取到
#   10 天逐日最高/最低温的源，保证自动化不中断。
# 墨迹天气(moji-weather) 的数据仅在浏览器渲染后由 app 接口动态下发，纯脚本
#   无法稳定无人值守抓取（实测无头 Chromium 渲染 90s+ 超时未吐 DOM），故未采用。
# 若改用国内源：到 dev.qweather.com 注册免费 key，把 fetch() 换成和风天气 15d 接口
#   https://devapi.qweather.com/v7/weather/15d?location=<adcode>&key=<KEY>
#   location 用 海伦=101050504 / 梨树=101060403，解析 daily 的 tempMax/tempMin/weather 即可。
# ======================================================================
CITIES = {
    "海伦市": (47.4595, 126.9430),
    "梨树县": (43.3000, 124.3300),
}
FIELDS = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_probability_max,wind_speed_10m_max,weather_code"
# 采用中国气象局标准天气预报用语（基于 WMO 天气代码）
WCODE = {
    0:"晴",1:"晴间多云",2:"多云",3:"阴",
    45:"雾",48:"雾凇",
    51:"小雨",53:"小雨",55:"小雨",
    56:"冻雨",57:"冻雨",
    61:"小雨",63:"中雨",65:"大雨",
    66:"冻雨",67:"冻雨",
    71:"小雪",73:"中雪",75:"大雪",77:"米雪",
    80:"阵雨",81:"阵雨",82:"强阵雨",
    85:"阵雪",86:"阵雪",
    95:"雷阵雨",96:"雷阵雨伴冰雹",99:"雷阵雨伴冰雹",
}
THRESH = 6.0  # 连续3天滑动窗口内最高温跨度阈值(°C)，"以上"含6
DTR_THRESH = 10.0  # 单日最高气温与最低气温温差阈值(°C)，严格大于10

def fetch(name, lat, lon):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&daily={FIELDS}&timezone=Asia%2FShanghai&forecast_days=10")
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["daily"]

def analyze(daily):
    tmax = daily["temperature_2m_max"]
    tmin = daily["temperature_2m_min"]
    dates = daily["time"]
    n = len(dates)
    windows = []
    for i in range(1, n-2):  # 从明天起算，排除当天窗口（晚上预警只看未来）
        w = tmax[i:i+3]
        span = max(w) - min(w)
        windows.append({"span": span, "lo": min(w), "hi": max(w),
                        "d0": dates[i], "d2": dates[i+2], "vals": w})
    triggered = any(w["span"] >= THRESH for w in windows)
    dod = [(dates[i], tmax[i]-tmax[i-1]) for i in range(1, n)]
    maxdod = max(abs(d[1]) for d in dod)
    # 单日温差（最高 - 最低），从明天起算，排除当天
    dtr_list = [(dates[i], tmax[i]-tmin[i]) for i in range(1, n)]
    dtr_trig = any(v > DTR_THRESH for _, v in dtr_list)
    return windows, triggered, dod, maxdod, dtr_list, dtr_trig

report = []
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
today_str = datetime.datetime.now().strftime('%Y-%m-%d')
report.append("# 气温波动预警 · 海伦 / 梨树")
report.append("")
report.append(f"> 生成时间：{now}（GMT+8） ｜ 监测窗口：未来10天 ｜ 数据来源：Open-Meteo 数值预报")
report.append(f"> 触发规则：连续 3 天滑动窗口内**最高气温跨度 ≥ 6°C**，**或**单日**最高气温与最低气温温差 > 10°C**，任一满足即推送。")
report.append("")

overall_trigger = False
city_results = {}
for name,(lat,lon) in CITIES.items():
    daily = fetch(name, lat, lon)
    windows, trig, dod, maxdod, dtr_list, dtr_trig = analyze(daily)
    overall_trigger = overall_trigger or trig or dtr_trig
    city_results[name] = (daily, windows, trig, dod, maxdod, dtr_list, dtr_trig)

    report.append(f"## {name}")
    report.append("")
    report.append("| 日期 | 最高℃ | 最低℃ | 均温℃ | 降水概率 | 最大风速(km/h) | 天气 |")
    report.append("|------|------|------|------|--------|-------------|------|")
    for i,d in enumerate(daily["time"]):
        if d == today_str:
            continue  # 晚上刷新不显示当天天气
        wc = WCODE.get(daily["weather_code"][i], str(daily["weather_code"][i]))
        pp = daily["precipitation_probability_max"][i]
        pp_s = f"{pp}%" if pp is not None else "-"
        ws = daily["wind_speed_10m_max"][i]
        ws_s = f"{ws}" if ws is not None else "-"
        report.append(f"| {d} | {daily['temperature_2m_max'][i]} | {daily['temperature_2m_min'][i]} | {daily['temperature_2m_mean'][i]} | {pp_s} | {ws_s} | {wc} |")
    report.append("")

    if trig:
        report.append(f"**⚠️ 已触发**：检测到连续3天最高气温跨度 ≥ 6°C 的窗口如下：")
        report.append("")
        report.append("| 窗口(连续3天) | 该窗口最高温℃ | 该窗口最低温℃ | 跨度℃ |")
        report.append("|--------------|--------------|--------------|------|")
        for w in windows:
            if w["span"] >= THRESH:
                report.append(f"| {w['d0']} ~ {w['d2']} | {w['hi']} | {w['lo']} | **{w['span']:.1f}** |")
        report.append("")
        big = [(d,delta) for d,delta in dod if abs(delta) >= 6]
        if big:
            parts = []
            for d,delta in big:
                arrow = "↑" if delta>0 else "↓"
                parts.append(f"{d} {arrow}{abs(delta):.1f}°C")
            report.append(f"单日最高气温跳动 ≥6°C：{'；'.join(parts)}。")
            report.append("")
    else:
        report.append(f"**✅ 未触发**：连续3天最高气温最大跨度为 {max(w['span'] for w in windows):.1f}°C（< 6°C 阈值）。")
        report.append("")

    # 单日温差（最高-最低）> 10℃ 预警
    dtr_big = [(d, v) for d, v in dtr_list if v > DTR_THRESH]
    if dtr_big:
        report.append(f"**🌡️ 单日温差预警**：以下日期**最高气温与最低气温温差 > {DTR_THRESH:.0f}°C**：")
        report.append("")
        report.append("| 日期 | 天气 | 最高℃ | 最低℃ | 温差℃ |")
        report.append("|------|------|------|------|------|")
        for d, v in dtr_big:
            i = daily["time"].index(d)
            wc = WCODE.get(daily["weather_code"][i], str(daily["weather_code"][i]))
            report.append(f"| {d} | {wc} | {daily['temperature_2m_max'][i]} | {daily['temperature_2m_min'][i]} | **{v:.1f}** |")
        report.append("")
    else:
        report.append(f"**✅ 单日温差**：最大温差为 {max(v for _, v in dtr_list):.1f}°C（≤ {DTR_THRESH:.0f}°C 阈值）。")
        report.append("")

report.append("---")
report.append("")
if overall_trigger:
    report.append("## 综合结论：⚠️ 触发预警（至少一个城市波动超标）")
else:
    report.append("## 综合结论：✅ 本期未触发（两城均无连续3天 ≥6°C 波动，且单日温差均 ≤10°C）")
report.append("")

report.append("### 🐷 猪群环控建议（按温差分型）")
# 汇总全表三轴指标
_all_lo = []
_all_dtr = []
_max_span = 0.0
for name in CITIES:
    daily, windows, trig, dod, maxdod, dtr_list, dtr_trig = city_results[name]
    _all_lo += list(daily["temperature_2m_min"])
    _all_dtr += [v for _, v in dtr_list]
    _max_span = max(_max_span, max(w["span"] for w in windows))
_tmin = min(_all_lo) if _all_lo else None
_max_dtr = max(_all_dtr) if _all_dtr else 0
if _tmin is not None:
    if _tmin <= 0:
        report.append(f"- **绝对低温·严寒**（最低 {_tmin}℃）：仔猪保温箱 32-34℃、保育/产房暖风地暖，水管防冻、防冷应激腹泻。")
    elif _tmin <= 5:
        report.append(f"- **绝对低温·低温**（最低 {_tmin}℃）：夜间密闭门窗、开保温灯、垫料加厚、保育舍局部加温。")
    elif _tmin <= 10:
        report.append(f"- **绝对低温·偏凉**（最低 {_tmin}℃）：关注夜间保温、产房维持恒温。")
    else:
        report.append(f"- **绝对低温·温和**（最低 {_tmin}℃）：维持常规环控即可。")
if _max_span >= 10:
    report.append(f"- **连续天气变化·剧烈**（连续3天最高温跨度 {_max_span:.0f}℃）：寒潮/强回暖，提前 48h 检修保温、平稳加温脱温、暂停转群与免疫。")
elif _max_span >= 6:
    report.append(f"- **连续天气变化·明显**（连续3天最高温跨度 {_max_span:.0f}℃）：关注升降温趋势，产房温度平稳过渡、防骤冷。")
if _max_dtr >= 15:
    report.append(f"- **当日温差·极大**（昼夜 {_max_dtr:.0f}℃）：间歇通风、防冷风直吹、夜间加饲、巡栏盯呼吸道病。")
elif _max_dtr >= 10:
    report.append(f"- **当日温差·偏大**（昼夜 {_max_dtr:.0f}℃）：间歇通风、防冷风直吹、巡栏盯采食量与喷嚏。")
report.append("")

report.append("### 通用提示")
report.append("- **穿衣**：东北昼夜温差大，采用「洋葱式」叠穿（长袖+外套），早晚加薄绒/防风层。")
report.append("- **健康**：气温骤变易诱发呼吸道与心脑血管不适，老人儿童及慢病患者注意增减衣物、保持通风。")
report.append("- **出行**：关注降水与大风时段，备好雨具；场区作业留意湿滑与低温时段。")
report.append("- **猪场生产提示**：强冷空气过境猪群易发冷应激与呼吸道病；建议提前检修保育/产房保温设备，关注昼夜温差，巡栏留意采食量与喷嚏增多。")
report.append("")

report.append("### 📲 微信 Server酱 推送文案（仅预警区域·简单播报）")
# 推送文案：仅「已触发」城市，简单播报逐日最高/最低温+天气，未触发城市不出现
lines = ["【气温波动预警】海伦·梨树 监测（仅播报预警区域）："]
for name in CITIES:
    daily, windows, trig, dod, maxdod, dtr_list, dtr_trig = city_results[name]
    if not (trig or dtr_trig):
        continue  # 未触发城市不进推送
    seen = set()
    if trig:
        lines.append(f"🔴 {name}：连续3天最高温跨度≥6℃，请注意气温波动")
        for w in windows:
            if w["span"] < THRESH:
                continue
            i0 = daily["time"].index(w["d0"])
            i2 = daily["time"].index(w["d2"])
            for i in range(i0, i2 + 1):
                d = daily["time"][i]
                if d in seen:
                    continue
                seen.add(d)
                wc = WCODE.get(daily["weather_code"][i], str(daily["weather_code"][i]))
                lines.append(f"• {d} {wc} 最高{daily['temperature_2m_max'][i]}℃ 最低{daily['temperature_2m_min'][i]}℃")
    if dtr_trig:
        dtr_big = [(d, v) for d, v in dtr_list if v > DTR_THRESH]
        lines.append(f"🟠 {name}：单日最高最低温差>10℃")
        for d, v in dtr_big:
            i = daily["time"].index(d)
            wc = WCODE.get(daily["weather_code"][i], str(daily["weather_code"][i]))
            lines.append(f"• {d} {wc} 最高{daily['temperature_2m_max'][i]}℃ 最低{daily['temperature_2m_min'][i]}℃ 温差{v:.0f}℃")
    lines.append("")
lines.append("提示：昼夜温差大，洋葱式穿衣；猪场提前保温防应激。")
report.append("> " + "\n> ".join(lines))
report.append("")

md = "\n".join(report)
out_name = "weather-alert-" + datetime.datetime.now().strftime('%Y-%m-%d') + ".md"
with open(out_name,"w",encoding="utf-8") as f:
    f.write(md)

# ---- 生成图片卡片 + Server酱 推送 ----
if overall_trigger:
    if PIL_OK:
        card_path = "alert-card-" + datetime.datetime.now().strftime('%Y-%m-%d') + ".png"
        triggered = []
        for name in CITIES:
            daily, windows, trig, dod, maxdod, dtr_list, dtr_trig = city_results[name]
            if not (trig or dtr_trig):
                continue
            rows_map = {}
            def add_row(i, dtr=None):
                d = daily["time"][i]
                wc = WCODE.get(daily["weather_code"][i], str(daily["weather_code"][i]))
                cur = rows_map.get(d, {})
                rows_map[d] = {"date": d[5:], "weather": wc,
                               "hi": daily["temperature_2m_max"][i],
                               "lo": daily["temperature_2m_min"][i],
                               "dtr": dtr if dtr is not None else cur.get("dtr")}
            if trig:
                for w in windows:
                    if w["span"] < THRESH:
                        continue
                    i0 = daily["time"].index(w["d0"])
                    i2 = daily["time"].index(w["d2"])
                    for i in range(i0, i2 + 1):
                        add_row(i)
            if dtr_trig:
                for d, v in dtr_list:
                    if v > DTR_THRESH:
                        add_row(daily["time"].index(d), dtr=round(v))
            rows = [rows_map[d] for d in daily["time"] if d in rows_map and d != today_str]
            triggered.append({"name": name, "rows": rows})
        # 计算触发城市的最大连续3天最高温跨度（用于底部环控建议轴②）
        max_span_all = 0.0
        for name in CITIES:
            _, windows, trig, _, _, _, dtr_trig = city_results[name]
            if not (trig or dtr_trig):
                continue
            max_span_all = max(max_span_all, max(w["span"] for w in windows))
        make_card(card_path, triggered, max_span_all)
        print("CARD:", card_path)
    else:
        card_path = None
        print("CARD_SKIP: Pillow 不可用")

    # 推送：配置了 GitHub 图床则推图片，否则回退文字
    if GH_TOKEN and GH_REPO and card_path:
        url = upload_github(card_path, GH_TOKEN, GH_REPO, GH_BRANCH)
        if url:
            # 加时间戳参数绕过微信/代理缓存，确保每次重推都是最新卡片
            url_ts = f"{url}?t={int(time.time())}"
            desp = f"![气温波动预警]({url_ts})\n\n" + "\n".join(lines)
            res = push_serverchan("⚠️ 气温波动预警·海伦市/梨树县", desp)
            print("PUSH_IMG:", res)
        else:
            print("UPLOAD_FAIL: GitHub 上传失败，回退文字推送")
            res = push_serverchan("⚠️ 气温波动预警·海伦市/梨树县", "\n".join(lines))
            print("PUSH_RESULT:", res)
    else:
        res = push_serverchan("⚠️ 气温波动预警·海伦市/梨树县", "\n".join(lines))
        print("PUSH_RESULT:", res)
        if not (GH_TOKEN and GH_REPO):
            print("IMG_DISABLED: 未配置 GH_TOKEN/GH_REPO，暂以文字推送；填后自动改图片推送")
else:
    print("PUSH_SKIP: 本期未触发，不推送")

print("OVERALL_TRIGGER:", overall_trigger)
for name in CITIES:
    daily, windows, trig, dod, maxdod, dtr_list, dtr_trig = city_results[name]
    print(f"{name}: triggered={trig}, dtr_trig={dtr_trig}, max_window_span={max(w['span'] for w in windows):.1f}, max_dod={maxdod:.1f}")
    for w in windows:
        if w['span']>=THRESH:
            print(f"   window {w['d0']}~{w['d2']} span={w['span']:.1f} vals={w['vals']}")
    for d, v in dtr_list:
        if v > DTR_THRESH:
            print(f"   dtr {d} = {v:.1f}")
print("OK, report written", out_name)
