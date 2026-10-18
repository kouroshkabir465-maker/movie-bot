#!/usr/bin/env python3
"""Legal movie bot (Farsi). New releases: Apple iTunes top-movie feeds (key-less) + IMDb rating via Wikidata->IMDb public dataset.
Free movies: public-domain feature films from Internet Archive. No pirated content.
  movie_bot.py --daily | --new | --free | --check | --welcome   [--dry]"""
import os, sys, re, json, time, html, gzip, random, datetime as dt, requests
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__)); TZ = ZoneInfo("Europe/Istanbul")
TOKEN = os.environ.get("MOVIE_TELEGRAM_BOT_TOKEN", "")
CHATS = [c.strip() for c in os.environ.get("MOVIE_CHAT_IDS", "8561650547,5728075440").split(",") if c.strip()]
ASK = os.environ.get("TG_CHAT", "").strip()
SEEN = os.path.join(HERE, "seen.json"); DRY = "--dry" in sys.argv
UA = {"User-Agent": "Mozilla/5.0 (movie-bot; legal sources only)"}
KB = json.dumps({"keyboard": [[{"text": "🎬 فیلم‌های جدید"}, {"text": "🎞 فیلم رایگان"}], [{"text": "🔍 بررسی کن"}]],
                 "resize_keyboard": True, "is_persistent": True})
GENRE_FA = {"Action & Adventure": "اکشن و ماجراجویی", "Comedy": "کمدی", "Drama": "درام", "Horror": "ترسناک", "Thriller": "هیجان‌انگیز",
            "Sci-Fi & Fantasy": "علمی‌تخیلی و فانتزی", "Kids & Family": "خانوادگی", "Romance": "عاشقانه", "Documentary": "مستند",
            "Animation": "انیمیشن", "Western": "وسترن", "Independent": "مستقل", "Music": "موزیکال", "Sports": "ورزشی"}

def tr(text):
    if not text: return ""
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single", timeout=15, headers=UA,
                         params=dict(client="gtx", sl="en", tl="fa", dt="t", q=text[:1500]))
        if r.ok and r.text.startswith("["): return "".join(p[0] for p in r.json()[0] if p[0]).strip()
    except Exception: pass
    try:
        j = requests.get("https://api.mymemory.translated.net/get", timeout=15, params={"q": text[:480], "langpair": "en|fa"}).json()
        t = j.get("responseData", {}).get("translatedText")
        if j.get("responseStatus") == 200 and t and "MYMEMORY" not in t.upper(): return t
    except Exception: pass
    return text

def short(x, n):
    x = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
    return x if len(x) <= n else x[:n].rsplit(" ", 1)[0] + "…"

# ---------- new releases (Apple iTunes RSS, key-less) ----------
def itunes(genre=None, n=25):
    u = f"https://itunes.apple.com/us/rss/topmovies/limit={n}" + (f"/genre={genre}" if genre else "") + "/json"
    out = []
    for e in requests.get(u, timeout=25, headers=UA).json()["feed"].get("entry", []):
        img = e["im:image"][-1]["label"]; img = re.sub(r"/\d+x\d+bb\.", "/600x900bb.", img)
        rd = e.get("im:releaseDate", {}).get("label", "")[:10]
        out.append(dict(id="it" + e["id"]["attributes"]["im:id"], title=e["im:name"]["label"], year=rd[:4], date=rd,
                        genre=e.get("category", {}).get("attributes", {}).get("label", ""), plot=e.get("summary", {}).get("label", ""),
                        poster=img, apple=e["id"]["label"].split("?")[0], price=e.get("im:price", {}).get("label", ""),
                        rent=e.get("im:rentalPrice", {}).get("label", ""), director=e.get("im:artist", {}).get("label", "")))
    return out

def imdb_ids(movies):
    """Wikidata SPARQL: English label + year -> IMDb id (key-less)."""
    if not movies: return {}
    vals = " ".join(json.dumps(m["title"]) + "@en" for m in movies)
    q = f"""SELECT ?l ?imdb ?d WHERE {{ VALUES ?l {{ {vals} }} ?f rdfs:label ?l; wdt:P31 wd:Q11424; wdt:P345 ?imdb; wdt:P577 ?d.
            FILTER(YEAR(?d) >= {dt.date.today().year - 2}) }}"""
    try:
        r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"}, headers=UA, timeout=40).json()
        return {b["l"]["value"]: b["imdb"]["value"] for b in r["results"]["bindings"]}
    except Exception as e:
        print("wikidata failed:", e); return {}

def imdb_ratings(ids):
    """IMDb public dataset title.ratings.tsv.gz (free for personal use) -> {tconst: (rating, votes)}."""
    want = set(ids)
    if not want: return {}
    out = {}
    try:
        with requests.get("https://datasets.imdbws.com/title.ratings.tsv.gz", stream=True, timeout=60, headers=UA) as r:
            for line in gzip.GzipFile(fileobj=r.raw):
                t = line.split(b"\t", 1)[0].decode()
                if t in want:
                    _, rt, v = line.decode().strip().split("\t"); out[t] = (rt, v)
                    if len(out) == len(want): break
    except Exception as e: print("imdb ratings failed:", e)
    return out

def new_releases(seen, n=3):
    action = itunes(4401); allm = itunes()
    pool, ids = [], set()
    for m in action[:15] + allm:   # emphasis on action, then other genres
        if m["id"] in ids: continue
        ids.add(m["id"]); pool.append(m)
    fresh = [m for m in pool if m["id"] not in seen]
    act = [m for m in fresh if "Action" in m["genre"]]
    pick = act[:2] + [m for m in fresh if m not in act[:2]][: n - len(act[:2])]
    if len(pick) < n: pick += [m for m in pool if m not in pick][: n - len(pick)]   # exhausted -> repeat best
    imdb = imdb_ids(pick); rat = imdb_ratings(imdb.values())
    for m in pick:
        t = imdb.get(m["title"]); m["imdb"] = t; m["rating"] = rat.get(t) if t else None
    return pick

def new_caption(m):
    g = GENRE_FA.get(m["genre"], m["genre"])
    rating = f"⭐️ IMDb: <b>{m['rating'][0]}</b>/10 ({int(m['rating'][1]):,} رأی)" if m.get("rating") else "⭐️ IMDb: هنوز امتیاز کافی نداره"
    links = [f'<a href="https://www.youtube.com/results?search_query={quote_plus(m["title"] + " " + m["year"] + " official trailer")}">🎥 تریلر (یوتیوب)</a>']
    if m.get("imdb"): links.append(f'<a href="https://www.imdb.com/title/{m["imdb"]}/">IMDb</a>')
    watch = f'🍿 <b>تماشای قانونی:</b> <a href="{m["apple"]}">Apple TV</a>' + (f" (اجاره {m['rent']} | خرید {m['price']})" if m.get("rent") else "") + \
            f' | <a href="https://www.justwatch.com/us/search?q={quote_plus(m["title"])}">JustWatch (همهٔ سرویس‌ها)</a>'
    head = f"🎬 <b>{html.escape(m['title'])}</b> ({m['year']})\n🎭 ژانر: {html.escape(g)}" + (f" | 🎬 کارگردان: {html.escape(m['director'])}" if m.get("director") else "") + \
           f"\n{rating}\n📅 انتشار دیجیتال: {m['date']}\n"
    tail = "\n" + " | ".join(links) + "\n" + watch
    plot = html.escape(short(tr(short(m["plot"], 600)), max(80, 1000 - len(head) - len(tail))))
    return head + "\n📝 " + plot + tail

# ---------- free public-domain films (Internet Archive) ----------
IA_Q = ('collection:feature_films AND licenseurl:*publicdomain* AND mediatype:movies AND '
        '(subject:action OR subject:western OR subject:"sci-fi" OR subject:"science fiction" OR subject:adventure OR subject:crime OR subject:thriller OR subject:war)')
def free_movie(seen):
    page = random.randint(1, 6)
    r = requests.get("https://archive.org/advancedsearch.php", timeout=30, headers=UA, params={
        "q": IA_Q, "fl[]": ["identifier", "title", "year", "description", "subject"], "sort[]": "downloads desc", "rows": 50, "page": page, "output": "json"}).json()
    docs = [d for d in r["response"]["docs"] if "ia" + d["identifier"] not in seen] or r["response"]["docs"]
    d = random.choice(docs[:20]); ident = d["identifier"]
    meta = requests.get(f"https://archive.org/metadata/{ident}", timeout=30, headers=UA).json()
    mp4 = sorted([f for f in meta.get("files", []) if f["name"].lower().endswith(".mp4") and f.get("size")], key=lambda f: int(f["size"]))
    desc = d.get("description") or meta.get("metadata", {}).get("description") or ""
    if isinstance(desc, list): desc = " ".join(desc)
    subj = d.get("subject") or []; subj = subj if isinstance(subj, list) else [subj]
    return dict(id="ia" + ident, ident=ident, title=short(d.get("title", ident), 120), year=str(d.get("year") or ""), desc=short(desc, 700),
                subjects=", ".join(subj[:4]), poster=f"https://archive.org/services/img/{ident}",
                page=f"https://archive.org/details/{ident}",
                mp4=(f"https://archive.org/download/{ident}/{quote_plus(mp4[0]['name']).replace('+', '%20')}" if mp4 else None),
                size=int(mp4[0]["size"]) if mp4 else None)

def free_caption(f):
    size = f" ({f['size'] / 1e6:.0f} مگابایت)" if f.get("size") else ""
    head = f"🎞 <b>فیلم رایگان و قانونی (مالکیت عمومی)</b>\n\n🎬 <b>{html.escape(f['title'])}</b>" + (f" ({f['year']})" if f["year"] else "") + \
           (f"\n🎭 موضوع: {html.escape(f['subjects'])}" if f["subjects"] else "") + "\n"
    tail = f'\n▶️ <a href="{f["page"]}">تماشای آنلاین در Internet Archive</a>' + (f'\n⬇️ <a href="{f["mp4"]}">دانلود مستقیم MP4</a>{size}' if f.get("mp4") else "") + \
           "\n✅ این فیلم در مالکیت عمومیه و تماشا و دانلودش قانونیه."
    plot = html.escape(short(tr(f["desc"]), max(60, 1000 - len(head) - len(tail)))) if f["desc"] else ""
    return head + (f"\n📝 {plot}\n" if plot else "") + tail

# ---------- telegram ----------
def targets(): return [ASK] if ASK in CHATS else CHATS
def api(method, c, files=None, **d):
    if DRY: print(f"[dry] {method} -> {c}: {(d.get('caption') or d.get('text') or '')[:2000]}\n"); return {"ok": True}
    try: return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", timeout=120, files=files,
                              data=dict(chat_id=c, reply_markup=KB, **d)).json()
    except Exception as e: return {"ok": False, "description": str(e)}

def send_item(c, photo, cap):
    if photo and api("sendPhoto", c, photo=photo, caption=cap, parse_mode="HTML").get("ok"): return True
    return api("sendMessage", c, text=cap, parse_mode="HTML", disable_web_page_preview="true").get("ok")

def send_video(c, f):
    """Upload the public-domain file itself when it fits the bot limit (50 MB)."""
    if not f.get("mp4") or not f.get("size") or f["size"] > 49e6 or DRY: return
    try:
        data = requests.get(f["mp4"], timeout=180, headers=UA).content
        j = api("sendVideo", c, files={"video": (f["ident"] + ".mp4", data)}, caption=f"🎞 {f['title']}", supports_streaming="true")
        print("video:", "ok" if j.get("ok") else j.get("description"))
    except Exception as e: print("video failed:", e)

def run(mode):
    seen = json.load(open(SEEN)) if os.path.exists(SEEN) else {}
    now = time.time()
    if mode == "daily" and now - seen.get("_last_daily", 0) < 2 * 3600 and not os.environ.get("FORCE"):
        print("daily already sent in last 2h, skip"); return
    news = new_releases(seen, 3 if mode in ("daily", "new", "check") else 0) if mode != "free" else []
    free = free_movie(seen) if mode in ("daily", "free", "check") else None
    ok_any = False
    for c in targets():
        if mode == "daily":
            j = api("sendMessage", c, text=f"🍿 <b>پیشنهاد فیلم امروز</b> — {dt.datetime.now(TZ):%Y-%m-%d}\nفیلم‌های جدید و پرطرفدار (بیشتر اکشن) + یک فیلم رایگان قانونی", parse_mode="HTML")
            if not j.get("ok"): print(f"send to {c} failed: {j.get('description')}"); continue
        delivered = 0
        for m in news: delivered += bool(send_item(c, m["poster"], new_caption(m)))
        if free:
            delivered += bool(send_item(c, free["poster"], free_caption(free))); send_video(c, free)
        if delivered: ok_any = True; print(f"sent to {c}: {delivered} items")
        else: print(f"send to {c} failed")
    if not ok_any: sys.exit("no recipient received anything")
    for m in news: seen[m["id"]] = now
    if free: seen[free["id"]] = now
    if mode == "daily": seen["_last_daily"] = now
    seen = {k: v for k, v in seen.items() if now - v < 120 * 86400}
    if not DRY: json.dump(seen, open(SEEN, "w"))

def welcome():
    msg = ("سلام داداش 🎬 به ربات فیلم خوش اومدی!\n\n"
           "• هر روز ساعت ۲۰:۰۰ فیلم‌های جدید و پرطرفدار دنیا (بیشتر اکشن) با پوستر، امتیاز IMDb، خلاصهٔ فارسی، تریلر و جای تماشای قانونی\n"
           "• فیلم‌های رایگان و کاملاً قانونی (مالکیت عمومی) از Internet Archive با لینک تماشا/دانلود\n\n"
           "دکمه‌ها: «🎬 فیلم‌های جدید»، «🎞 فیلم رایگان»، «🔍 بررسی کن»")
    for c in targets():
        j = api("sendMessage", c, text=msg); print(f"welcome {c}:", "ok" if j.get("ok") else j.get("description"))

if __name__ == "__main__":
    if "--welcome" in sys.argv: welcome()
    else: run(next((m for m in ("daily", "new", "free", "check") if f"--{m}" in sys.argv), "check"))
