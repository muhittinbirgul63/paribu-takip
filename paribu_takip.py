"""
Paribu Değişim Takip Botu - 3 Ayrı Mesaj (20dk, 1sa, 2sa)
"""

import requests
import time
import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TZ_TR = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")
ADMIN_ID       = str(os.getenv("ADMIN_ID", "1072335473"))

GUNCELLEME_SURESI = 10
VERI_SURESI       = 5
KAYIT_SURESI      = 120

PERIYOTLAR = {
    "20dk": 1200,
    "1sa":  3600,
    "2sa":  7200,
}

snap        = {p: {} for p in PERIYOTLAR}
snap_zamani = {p: 0  for p in PERIYOTLAR}

# Her periyot için ayrı mesaj ID
mesaj_idler    = {p: None for p in PERIYOTLAR}
kayit_mesaj_id = None
son_guncelleme = 0
son_kayit      = 0


def paribu_fiyatlar():
    try:
        r = requests.get("https://www.paribu.com/ticker", timeout=10)
        sonuc = {}
        for parite, bilgi in r.json().items():
            if "_TL" in parite.upper():
                coin = parite.upper().replace("_TL", "")
                bid  = float(bilgi.get("highestBid", 0))
                if bid > 0:
                    sonuc[coin] = bid
        return sonuc
    except Exception as e:
        print(f"Paribu hata: {e}")
        return {}


def fiyat_formatla(fiyat):
    if fiyat >= 1000:    return f"{fiyat:,.2f}₺"
    elif fiyat >= 1:     return f"{fiyat:.3f}₺"
    elif fiyat >= 0.01:  return f"{fiyat:.4f}₺"
    else:                return f"{fiyat:.6f}₺"


def sure_formatla(saniye):
    sa = int(saniye // 3600)
    dk = int((saniye % 3600) // 60)
    sn = int(saniye % 60)
    if sa > 0:
        return f"{sa}sa {dk}dk"
    elif dk > 0:
        return f"{dk}dk {sn}sn"
    else:
        return f"{sn}sn"


def snap_guncelle(guncel, simdi):
    for periyot, sure in PERIYOTLAR.items():
        if snap_zamani[periyot] == 0 or simdi - snap_zamani[periyot] >= sure:
            snap[periyot] = {coin: (simdi, bid) for coin, bid in guncel.items()}
            snap_zamani[periyot] = simdi
            print(f"[SNAP] {periyot} snap alındı")


def degisim_hesapla(guncel, simdi, periyot):
    degisimler = []
    for coin, guncel_bid in guncel.items():
        if coin not in snap[periyot]:
            continue
        snap_zaman, snap_bid = snap[periyot][coin]
        gecen = simdi - snap_zaman
        if gecen < 10 or snap_bid <= 0:
            continue
        degisim = ((guncel_bid - snap_bid) / snap_bid) * 100
        degisimler.append((coin, degisim, guncel_bid))
    degisimler.sort(key=lambda x: x[1], reverse=True)
    return degisimler


def mesaj_olustur(degisimler, periyot, simdi):
    zaman    = datetime.now(TZ_TR).strftime("%H:%M:%S")
    gecen    = simdi - snap_zamani[periyot] if snap_zamani[periyot] > 0 else 0
    sure_str = sure_formatla(gecen)

    etiketler = {"20dk": "20 Dakika", "1sa": "1 Saat", "2sa": "2 Saat"}
    emojiler  = {"20dk": "🏃", "1sa": "⏰", "2sa": "🕰"}

    satirlar = [
        f"{emojiler[periyot]} <b>Paribu Yükselenler</b>",
        f"🕐 <i>Son {sure_str} ({etiketler[periyot]})</i>",
        "",
    ]

    for coin, deg, bid in degisimler[:10]:
        isaret = "+" if deg >= 0 else ""
        satirlar.append(f"🟢 <b>{coin}/TL</b>")
        satirlar.append(f"   <code>{isaret}{deg:.2f}%</code>  ›  <b>{fiyat_formatla(bid)}</b>")
        satirlar.append("")

    satirlar.append(f"<i>🔄 {zaman}</i>")
    return "\n".join(satirlar)


def telegram_gonder(mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        if r.json().get("ok"):
            return r.json()["result"]["message_id"]
        print(f"Telegram gönder hata: {r.json()}")
    except Exception as e:
        print(f"Telegram gönder hata: {e}")
    return None


def telegram_duzenle(msg_id, mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": CHAT_ID, "message_id": msg_id, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Telegram düzenle hata: {e}")
        return False


def kaydet():
    global kayit_mesaj_id
    try:
        veri = {
            "snap_zamani": snap_zamani,
            "mesaj_idler": mesaj_idler,
            "snap": {p: {c: list(v) for c, v in s.items()} for p, s in snap.items()},
        }
        metin = f"PARIBU_SNAP:{json.dumps(veri)}"
        if len(metin) > 4000:
            veri["snap"] = {}
            metin = f"PARIBU_SNAP:{json.dumps(veri)}"

        if kayit_mesaj_id is None:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": metin},
                timeout=10
            )
            if r.json().get("ok"):
                kayit_mesaj_id = r.json()["result"]["message_id"]
        else:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={"chat_id": ADMIN_ID, "message_id": kayit_mesaj_id, "text": metin},
                timeout=10
            )
    except Exception as e:
        print(f"[KAYIT HATA] {e}")


def yukle():
    global kayit_mesaj_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100}, timeout=10
        )
        for item in reversed(r.json().get("result", [])):
            mesaj = item.get("message", {})
            if str(mesaj.get("chat", {}).get("id", "")) == ADMIN_ID:
                metin = mesaj.get("text", "")
                if metin.startswith("PARIBU_SNAP:"):
                    try:
                        veri = json.loads(metin[12:])
                        simdi = time.time()
                        for p in PERIYOTLAR:
                            if p in veri.get("snap_zamani", {}):
                                snap_zamani[p] = veri["snap_zamani"][p]
                            if p in veri.get("mesaj_idler", {}):
                                mesaj_idler[p] = veri["mesaj_idler"][p]
                            if p in veri.get("snap", {}):
                                snap[p] = {c: tuple(v) for c, v in veri["snap"][p].items()}
                        kayit_mesaj_id = mesaj.get("message_id")
                        print(f"[YUKLE] Snap yüklendi")
                        return
                    except Exception as e:
                        print(f"[YUKLE HATA] {e}")
        print("[YUKLE] Snap bulunamadı")
    except Exception as e:
        print(f"[YUKLE HATA] {e}")


def bot_calistir():
    global son_guncelleme, son_kayit

    print("Paribu Takip Botu başlatılıyor...")
    yukle()

    while True:
        simdi = time.time()

        guncel = paribu_fiyatlar()
        if not guncel:
            time.sleep(VERI_SURESI)
            continue

        snap_guncelle(guncel, simdi)

        if simdi - son_kayit >= KAYIT_SURESI:
            kaydet()
            son_kayit = simdi

        if simdi - son_guncelleme >= GUNCELLEME_SURESI:
            for periyot in PERIYOTLAR:
                degisimler = degisim_hesapla(guncel, simdi, periyot)
                if not degisimler:
                    continue

                mesaj = mesaj_olustur(degisimler, periyot, simdi)

                if mesaj_idler[periyot] is None:
                    mesaj_idler[periyot] = telegram_gonder(mesaj)
                    print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] {periyot} ilk mesaj gönderildi!")
                else:
                    basari = telegram_duzenle(mesaj_idler[periyot], mesaj)
                    if not basari:
                        mesaj_idler[periyot] = telegram_gonder(mesaj)
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] {periyot} yeni mesaj gönderildi!")
                    else:
                        top = degisimler[0]
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] {periyot} güncellendi - Top: {top[0]} %{top[1]:.2f}")

            son_guncelleme = simdi

        time.sleep(VERI_SURESI)


if __name__ == "__main__":
    bot_calistir()
