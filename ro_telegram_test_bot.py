#!/usr/bin/env python3
import asyncio
import re
import hashlib
from collections import deque
import os
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage,
    DocumentAttributeVideo
)

from sentence_transformers import SentenceTransformer, util

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger("telethon").setLevel(logging.WARNING)

# ================= CONFIG =================
load_dotenv()
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "RU_session")

DESTINATION = "@testallnewsmd"
SEO_LIMIT = 4096 # limită pentru text simplu
MEDIA_LIMIT = 1024 # limită pentru caption la media
SEMANTIC_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.95"))
CYRILLIC_MAX_RATIO = float(os.getenv("CYRILLIC_MAX_RATIO", "0.05"))
MAX_MEMORY = 1000

# ================= AI =================
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# buffer clasic pentru ultimele 1000 mesaje
posted_embeddings = deque(maxlen=MAX_MEMORY)
posted_hashes = deque(maxlen=MAX_MEMORY)
posted_channels = deque(maxlen=MAX_MEMORY)
posted_links = deque(maxlen=MAX_MEMORY)

# listă pentru dedup pe 24h
posted_records = []

# ================= SOURCES =================
SOURCES = [
    "agoramd",
    "alertamd",
    "AvertizariSHS",
    "canal5_md",
    "Carabinieri_MD",
    "cecmoldova",
    "deschide_md",
    "igordodon",
    "ichicu",
    "indexMLD",
    "insidermd",
    "ionceban",
    "irinavlahofficial",
    "Jurnal_TV",
    "maeiexplica",
    "Moldova_20",
    "newtvmd",
    "NordNewsMD",
    "Omniapres",
    "OnetvMoldova",
    "ParlamentulRM",
    "partidulnostrumoldova",
    "Politia_Republicii_Moldova",
    "presedinta_md",
    "Primaria_Chisinau",
    "prima_sursa_md",
    "protv_chisinau_official",
    "psrmmd",
    "pulsmedia",
    "radumarian",
    "realitateamd",
    "realmorarinews",
    "ro_newsmakerlive",
    "ServiciulVamalRM",
    "spinuandrei",
    "sputnikmd_2",
    "stiridiez",
    "stirimd",
    "moldovatelegraph",
    "tribunamd",
    "tudorulianovschi",
    "tv8md",
    "tvnord",
    "ultimaoramd",
    "unimedia_info",
    "vasiletarlev",
    "Victoria_Furtuna",
    "viitorulmoldovei",
    "vladbiletchi",
    "vladfilat1",
    "vladplahotniucmd",
    "zdgmd",
    "ZiuaMoldova"
]

# ================= BRANDS =================
SOURCE_BRANDS = {
    "maeiexplica": "MAEIE",
    "agoramd": "Agora",
    "tvnord": "TV Nord",
    "ZiuaMoldova": "ZIUA - Ai dreptul să știi",
    "unimedia_info": "UNIMEDIA",
    "ro_newsmakerlive": "NewsMaker.md"
}

# ================= INIT =================
client = TelegramClient(SESSION_NAME, TG_API_ID, TG_API_HASH)
queue = asyncio.Queue()

# ================= HELPERS =================
def normalize(text: str) -> str:
    # transformă tot în lowercase
    text = text.lower()
    # elimină orice caracter care nu e literă/cifră/spațiu
    text = re.sub(r"[^\w\s]", " ", text)
    # înlocuiește spațiile multiple cu unul singur
    text = re.sub(r"\s+", " ", text).strip()
    return text

def cyrillic_ratio(text: str) -> float:
    if not text:
        return 0.0
    total = len(text)
    cyrillic = len(re.findall(r"[А-Яа-я]", text))
    return cyrillic / total if total else 0.0

def chat_name(chat):
    if chat.username:
        return f"@{chat.username}"
    return chat.title or "Canal necunoscut"

def message_link(chat, msg):
    if chat.username:
        return f"https://t.me/{chat.username}/{msg.id}"
    return f"ID {msg.id}"

def cleanup_records():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    global posted_records
    posted_records = [r for r in posted_records if r["time"] >= cutoff]

def add_record(hash_val, emb, channel, link):
    posted_records.append({
        "hash": hash_val,
        "embedding": emb,
        "channel": channel,
        "link": link,
        "time": datetime.now(timezone.utc)
    })

# ================= CAPTION 2=================
import re
import hashlib
from sentence_transformers import util

def clean_fixed_expressions(raw: str) -> str:
    FIXED_PATTERNS = [
    r"🔺\[Подписаться\]\(https://t\.me/canal5ru\)",
    r"\[@wtfmoldova\]",
    r"👌\[Подпишись на @primulinmd\]",
    r"@rusputnikmd_2",
    r"\[Подпишись на Moldova Liberă\]\(http.*?\)",
    r"Подпишитесь на Glossa.*",
    r"👀 \[Подпишись на Нетипичную Молдову\]\(https://t\.me/.*?\)",
    r"▶️\[YouTube\]\(https://www\.youtube\.com/.*?\)",
    r"▶️\[Facebook\]\(https://www\.facebook\.com/.*?\)",
    r"✔️\[Подпишись на ГРТ\]\(https://t\.me/gagauzreal\)",
    r"➖➖➖➖➖➖➖ @MIR24MOLDOVA \[Подпишись\]\(https://t\.me/MIR24MOLDOVA\)",
    r"👍\s+\[Salut Молдова! Подпишись\]\(https://t\.me/\+j_jWJqt6YvEwZjhk\)!",
    r"@enewsmd\s*👈\s*Подписывайтесь на наш канал",
    r"@cvtmd_bot\s*-\s*предложка",
    r"\[Молдова: Актуально\s*-\s*подписаться\]\(https://t\.me/Moldova_actualy\)",
    r"👍\s*\[Подпишись на Мир Гагаузии\]\(https://t\.me/mirgagauzia\)",
    r"@gagauziarun",
    r"@enewsmd",
    r"👉\s*Urmărește @ZiuaMoldova pe Telegram!",
    r"🔗\s*Citește mai mult",
    r"👁\s*\[Urmărește AGORA pe Telegram\]\(https://t\.me/agoramd\)",
    r"🔺\[Abonează-te\]\(https://t\.me/canal5_md\)",
    r"Rămâneți cu https://t\.me/ultimaoramd",
    r"Avem și versiune în rusă\s*–\s*abonează-te și citește!",
    r"🟥\s*\[Moldova 2\.0\]\(https://t\.me/Moldova_20/.*?\)"
]

    for pattern in FIXED_PATTERNS:
        raw = re.sub(pattern, "", raw, flags=re.IGNORECASE | re.MULTILINE)

    # 🔧 Normalizează whitespace-ul
    raw = re.sub(r"\n\s*\n+", "\n", raw) # elimină rânduri goale multiple
    return raw.strip()

# ================= CAPTION =================
def build_caption(msg, chat, media=None):
    raw = (msg.text or msg.raw_text or "").replace("**", "")
    if not raw.strip():
        return None

    link = message_link(chat, msg)

    # Filtru chirilic
    if cyrillic_ratio(raw) > CYRILLIC_MAX_RATIO:
        logging.warning(f"⛔ ️Mesaj ignorat din {chat_name(chat)} ({link}, cyrillic)")
        return None
    
    # Regula: blochează toate forwardurile (ca să nu mai apară dubluri)
    if msg.forward:
        logging.warning(f"⛔ Mesaj ignorat din {chat_name(chat)} ({link}), este forward")
        return None

    # Curățăm înregistrările mai vechi de 24h
    cleanup_records()

    # --- Elimină expresii fixe ---
    FIXED_EXPRESSIONS_RU = [
        "🔺[Подписаться](https://t.me/canal5ru)",
        "[@wtfmoldova]",
        "👌[Подпишись на @primulinmd]",
        "@rusputnikmd_2",
        "[Подпишись на Moldova Liberă](http://t.me/moldovalibera)",
        "Подпишитесь на Glossa 🤑",
        "👀 [Подпишись на Нетипичную Молдову](https://t.me/+7QQpZG8CzoYwMGQy)",
        "▶️[YouTube](https://www.youtube.com/live/1q_tklYHFEM?si=6xFUsKwSe3rQCem0)",
        "▶️[Facebook](https://www.facebook.com/share/v/1Bg7nmoWV3/)",
        "✔️[Подпишись на ГРТ](https://t.me/gagauzreal)",
        "➖➖➖➖➖➖➖ @MIR24MOLDOVA [Подпишись](https://t.me/MIR24MOLDOVA)",
        "👍  [Salut Молдova! Подпишись](https://t.me/+j_jWJqt6YvEwZjhk)!",
        "@enewsmd 👈 Подписывайтесь на наш канал",
        "@cvtmd_bot - предложка",
        "[Молдова: Актуально - подписаться](https://t.me/Moldova_actualy)",
        "👍 [Подпишись на Мир Гагаузии](https://t.me/mirgagauzia)",
        "@gagauziarun",
        "@enewsmd",
        "👉 Urmărește @ZiuaMoldova pe Telegram!",
        "🔗 Citește mai mult",
        "👁 [Urmărește AGORA pe Telegram](https://t.me/agoramd)",
        "🔺[Abonează-te](https://t.me/canal5_md)",
        "Rămâneți cu https://t.me/ultimaoramd",
        "Avem și versiune în rusă – abonează-te și citește!",
        "🟥 [Moldova 2.0](https://t.me/Moldova_20/)"
    ]
    for expr in FIXED_EXPRESSIONS_RU:
        raw = raw.replace(expr, "")

    # --- Truncare inteligentă ---
    limit = (MEDIA_LIMIT - 200) if msg.media else (SEO_LIMIT - 200)
    
    if len(raw) > limit:
        cutoff = raw.rfind('.', 0, limit)
        if cutoff == -1:
            cutoff = limit
        text = raw[:cutoff].strip()
        truncated = cutoff < len(raw)
    else:
        text = raw
        truncated = False

    if truncated:
        source_link = f"https://t.me/{chat.username}/{msg.id}"
        text += f'\n\n📖 [👉 citește mai departe aici 👈]({source_link})'

    if chat.username:
        source_link = f"https://t.me/{chat.username}/{msg.id}"
        brand = SOURCE_BRANDS.get(chat.username, chat.title or "Sursă")
        text += f'\n\nVia: [{brand}]({source_link})'
        text += '\n\n🔔 Prieteni, abonați-vă la [All News Moldova](https://t.me/allnewsmoldova)'
        text += '\n\n📢 Toate știrile în limba 🇷🇺 sunt aici: [All News Молдoвa](https://t.me/allnewsmoldova_ru)'

    # --- Asigură lungimea finală corectă ---
    final_limit = MEDIA_LIMIT if msg.media else SEO_LIMIT
    if len(text) > final_limit:
        text = text[:final_limit].rsplit('\n', 1)[0]

    # --- Deduplicare pe textul final ---
    h = hashlib.sha256(normalize(text).encode()).hexdigest()
    emb = model.encode(text, convert_to_tensor=True)

    for r in posted_records:
        if r["hash"] == h:
            logging.warning(f"⛔ Mesaj duplicat ignorat din {chat_name(chat)} ({link})")
            return None
        score = util.cos_sim(emb, r["embedding"]).item()
        logging.info(f"Comparat cu {r['channel']} scor={score:.2f}")
        if score >= SEMANTIC_THRESHOLD:
            logging.warning(f"⛔ Mesaj ignorat din {chat_name(chat)} ({link}), similar cu {r['channel']} ({r['link']})")
            return None
        if score >= 0.98 and r["channel"].replace("@","") in SOURCES and r["channel"] != chat.username:
            logging.warning(f"️⛔ Mesaj ignorat din {chat_name(chat)} ({link}), repost 1:1 de la {r['channel']}")
            return None

    add_record(h, emb, chat_name(chat), link)

    return text

# ================= MEDIA =================
def get_media(msg):
    if isinstance(msg.media, MessageMediaPhoto):
        return msg.media
    if isinstance(msg.media, MessageMediaDocument):
        for attr in msg.media.document.attributes or []:
            if isinstance(attr, DocumentAttributeVideo):
                return msg.media
        return msg.media
    return None

# ================= WORKER =================
async def worker():
    while True:
        text, media = await queue.get()
        try:
            if isinstance(media, MessageMediaWebPage):
                media = None
            await client.send_message(
                DESTINATION,
                text,
                file=media,
                parse_mode="markdown",
                link_preview=False
            )
            logging.info(f"✅ Postat în {DESTINATION}: {text[:50]}...")
        except RPCError as e:
            logging.error(f"Eroare la trimitere: {e}")
        queue.task_done()

# ================= HANDLER =================
@client.on(events.NewMessage(chats=["@" + s for s in SOURCES]))
async def handler(event):
    msg = event.message
    chat = await event.get_chat()

    # 🔒 Blochează toate forwardurile (inclusiv cele cu text sau media)
    if msg.forward:
        logging.warning(f"⛔ Ignorat în handler: forward din {chat_name(chat)} ({message_link(chat, msg)})")
        return

    media = msg.media
    caption = build_caption(msg, chat, media)
    if caption is None:
        return

    media = get_media(msg)
    await queue.put((caption, media))
    logging.info(f"📥 Mesaj procesat din {chat_name(chat)} ({message_link(chat, msg)}), pus în coadă")

# ================= MAIN =================
async def main():
    await client.start()
    asyncio.create_task(worker())
    logging.info("🇲🇩  BOT AllNewsMoldova (RO) PORNIT — COPY 1:1 + VIA + dedup 24h")
    await client.run_until_disconnected()

asyncio.run(main())
