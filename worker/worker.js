// Movie bot Telegram webhook + daily cron. Separate from other bots.
const ALLOWED = [8561650547, 5728075440];
const REPO = "kouroshkabir465-maker/movie-bot";
const KB = { keyboard: [[{ text: "🎬 فیلم‌های جدید" }, { text: "🎞 فیلم رایگان" }], [{ text: "🔍 بررسی کن" }]], resize_keyboard: true, is_persistent: true };
const modeOf = t => { t = t.trim();
  if (/🎬|جدید|^\/new\b/.test(t)) return "new";
  if (/🎞|رایگان|^\/free\b/.test(t)) return "free";
  if (/🔍|بررسی|^\/check\b/.test(t)) return "check";
  return null; };
const gh = (env, path, body) => fetch(`https://api.github.com/repos/${REPO}/${path}`, { method: "POST", body: JSON.stringify(body),
  headers: { authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "movie-bot-worker", "content-type": "application/json" } });

export default {
  // Cron 17:00 UTC = 20:00 Istanbul (GitHub cron is backup; bot skips if already sent <2h ago)
  async scheduled(event, env, ctx) { ctx.waitUntil(gh(env, "actions/workflows/daily.yml/dispatches", { ref: "main" })); },
  async fetch(req, env, ctx) {
    if (req.method !== "POST") return new Response("ok");
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
    let u; try { u = await req.json(); } catch { return new Response("bad", { status: 400 }); }
    const m = u.message || u.edited_message;
    if (!m || !m.chat || !ALLOWED.includes(m.chat.id)) return new Response("ignored");
    const chat = m.chat.id, mode = modeOf(m.text || "");
    const tg = (method, body) => fetch(`https://api.telegram.org/bot${env.MOVIE_TELEGRAM_BOT_TOKEN}/${method}`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!mode) {
      ctx.waitUntil(tg("sendMessage", { chat_id: chat, reply_markup: KB, text: "سلام داداش 🎬 یکی از دکمه‌ها رو بزن: «🎬 فیلم‌های جدید»، «🎞 فیلم رایگان» یا «🔍 بررسی کن». پیشنهاد روزانه هم ساعت ۲۰:۰۰ میاد." }));
      return new Response("ok");
    }
    ctx.waitUntil(Promise.all([
      tg("sendMessage", { chat_id: chat, text: "در حال بررسی… ⏳", reply_markup: KB, reply_parameters: { message_id: m.message_id, allow_sending_without_reply: true } }),
      gh(env, "dispatches", { event_type: "tg_cmd", client_payload: { mode, chat } }).then(async r => {
        if (r.status >= 300) await tg("sendMessage", { chat_id: chat, text: "⚠️ شروع نشد، چند دقیقه دیگه دوباره امتحان کن." }); }),
    ]));
    return new Response("ok");
  },
};
