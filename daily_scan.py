"""GitHub Actions 每日扫描脚本 — 拉实时行情、过滤涨停、推Telegram。"""
import urllib.request, urllib.parse, json, datetime as dt

TG_TOKEN = "8891262140:AAEDe-As4zW59GN-cp5nSyrt2M8nPeHtqrc"
TG_CHAT = "2098753325"
GAIN_MIN, GAIN_MAX = 9.0, 10.0
VOL_MIN = 3.0
SEAL_MIN = 0.998
OPEN_MAX = 5.0
MAX_PICKS = 3


def tg(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def main():
    print(f"开始扫描 {dt.datetime.now()}", flush=True)

    import requests
    params = {
        "pn": "1", "pz": "5000", "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f8,f10,f12,f14,f15,f16,f17",
    }
    try:
        r = requests.get("http://82.push2.eastmoney.com/api/qt/clist/get", params=params, timeout=20)
        items = r.json()["data"]["diff"]
    except Exception as e:
        tg(f"❌ 行情拉取失败: {e}")
        raise

    print(f"全市场 {len(items)} 只", flush=True)

    picks = []
    for item in items:
        code = item.get("f12", "")
        name = item.get("f14", "")
        price = float(item.get("f2", 0) or 0)
        pct = float(item.get("f3", 0) or 0)
        vol_ratio = float(item.get("f10", 0) or 0)
        high = float(item.get("f15", 0) or 0)
        open_p = float(item.get("f17", 0) or 0)

        if not code or price <= 0:
            continue
        if name.startswith(("ST", "*ST", "N", "C")):
            continue
        if not (GAIN_MIN <= pct <= GAIN_MAX):
            continue
        if vol_ratio < VOL_MIN:
            continue
        if high > 0 and price / high < SEAL_MIN:
            continue
        if open_p > 0 and price > 0:
            prev_close = price / (1 + pct / 100)
            if (open_p - prev_close) / prev_close * 100 >= OPEN_MAX:
                continue

        picks.append((code, name, price, pct, vol_ratio))

    picks.sort(key=lambda x: x[4], reverse=True)
    picks = picks[:MAX_PICKS]

    now = dt.datetime.now().strftime("%m-%d %H:%M")
    if not picks:
        tg(f"⚠️ 涨停板扫描 {now}\n今日无符合条件的涨停股")
        print("无推荐", flush=True)
    else:
        lines = [
            f"<b>🎯 涨停板尾盘推荐</b> — {now}",
            f"买入 14:50-14:57 | 卖出 次日开盘\n",
        ]
        for i, (code, name, price, pct, vol) in enumerate(picks):
            lines.append(
                f"<b>#{i + 1} {code} {name}</b>\n"
                f"现价 ¥{price:.2f}  +{pct:.1f}%  量比{vol:.1f}\n"
                f"买入 ¥{price:.2f}  止盈 >¥{price * 1.01:.2f}"
            )
        lines.append("\n⚠️ 量化筛选，不构成投资建议")
        tg("\n".join(lines))
        print(f"推荐 {len(picks)} 只", flush=True)


if __name__ == "__main__":
    main()
