"""
Paribu Değişim Takip Botu
- 20dk, 1sa, 2sa kolonları
- Restart olunca Telegram'dan geçmiş okur
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

# Her periyot için snap zamanları (saniye)
PERIYOTLAR = {
    "20dk": 1200,
    "1sa":  3600,
    "2sa":  7200,
}

# {periyot: {coin: (timestamp, bid)}} - snap fiyatları
snap = {p: {} for p in PERIYOTLAR}
snap_zamani = {p: 0 for p in PERIYOTLAR}

mesaj_id       = None
kayit_mesaj_id = None
son_guncelleme = 0
son_kayit      = 0
KAYIT_SURESI   = 120  # 2 dakikada bir kaydet


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
    if fiyat >= 1000:    return f"{fiyat:,.0f}₺"
    elif fiyat >= 10:    return f"{fiyat:.2f}₺"
    elif fiyat >= 1:     return f"{fiyat:.3f}₺"
    elif fiyat >= 0.01:  return f"{fiyat:.4f}₺"
    else:                return f"{fiyat:.6f}₺"


def snap_guncelle(guncel, simdi):
    """Her periyot için snap fiyatlarını güncelle"""
    for periyot, sure in PERIYOTLAR.items():
        # İlk kez veya periyot doldu
        if snap_zamani[periyot] == 0 or simdi - snap_zamani[periyot] >= sure:
            snap[periyot] = {coin: (simdi, bid) for coin, bid in guncel.items()}
            snap_zamani[periyot] = simdi
            print(f"[SNAP] {periyot} snap alındı - {len(snap[periyot])} coin")


def degisim_hesapla(guncel, simdi):
    """Her periyot için değişimleri hesapla"""
    sonuclar = {}
    for periyot in PERIYOTLAR:
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
        sonuclar[periyot] = degisimler
    return sonuclar


def mesaj_olustur(degisimler_dict, simdi):
    zaman = datetime.now(TZ_TR).strftime("%H:%M:%S")

    # Her periyot için süre hesapla
    sure_str = {}
    for periyot, sure in PERIYOTLAR.items():
        gecen = simdi - snap_zamani[periyot] if snap_zamani[periyot] > 0 else 0
        dk = int(gecen // 60)
        sa = int(dk // 60)
        if sa > 0:
            sure_str[periyot] = f"{sa}sa{dk%60}dk"
        else:
            sure_str[periyot] = f"{dk}dk"

    # Başlık
    baslik = (
        f"📊 <b>Paribu Yükselenler</b>\n"
        f"<code>"
        f"{'20dk':^14}{'1sa':^14}{'2sa':^14}\n"
        f"{'─'*42}\n"
    )

    # Her satır için 3 kolonu yan yana yaz
    satirlar = []
    max_satir = 10
    d20 = degisimler_dict.get("20dk", [])[:max_satir]
    d1s = degisimler_dict.get("1sa",  [])[:max_satir]
    d2s = degisimler_dict.get("2sa",  [])[:max_satir]

    for i in range(max_satir):
        def kolon(liste, idx):
            if idx < len(liste):
                coin, deg, _ = liste[idx]
                isaret = "+" if deg >= 0 else ""
                return f"{coin[:7]:<7} {isaret}{deg:.2f}%"
            return " " * 16

        satir = f"{kolon(d20,i):<16}  {kolon(d1s,i):<16}  {kolon(d2s,i):<16}"
        satirlar.append(satir)

    icerik = "\n".join(satirlar)
    bitis = f"\n</code><i>🔄 {zaman}</i>"

    return baslik + icerik + bitis


def kaydet():
    """Snap verilerini Telegram'a kaydet"""
    global kayit_mesaj_id
    try:
        veri = {
            "snap": {p: {c: list(v) for c, v in s.items()} for p, s in snap.items()},
            "snap_zamani": snap_zamani,
        }
        metin = f"PARIBU_SNAP:{json.dumps(veri)}"
        # 4096 karakter limitini aş
        if len(metin) > 4000:
            # Sadece son snap'i kaydet
            veri2 = {"snap": {}, "snap_zamani": snap_zamani}
            for p in PERIYOTLAR:
                coins = list(snap[p].items())[-100:]
                veri2["snap"][p] = {c: list(v) for c, v in coins}
            metin = f"PARIBU_SNAP:{json.dumps(veri2)}"

        if kayit_mesaj_id is None:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": metin},
                timeout=10
            )
            if r.json().get("ok"):
                kayit_mesaj_id = r.json()["result"]["message_id"]
                print(f"[KAYIT] Snap kaydedildi (msg_id: {kayit_mesaj_id})")
        else:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={"chat_id": ADMIN_ID, "message_id": kayit_mesaj_id, "text": metin},
                timeout=10
            )
            print(f"[KAYIT] Snap güncellendi")
    except Exception as e:
        print(f"[KAYIT HATA] {e}")


def yukle():
    """Telegram'dan snap verilerini yükle"""
    global kayit_mesaj_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100},
            timeout=10
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
                            if p in veri.get("snap", {}):
                                snap[p] = {c: tuple(v) for c, v in veri["snap"][p].items()}
                            if p in veri.get("snap_zamani", {}):
                                eski_zaman = veri["snap_zamani"][p]
                                # Snap zamanını güncelle — geçen süreyi hesaba kat
                                snap_zamani[p] = eski_zaman
                        kayit_mesaj_id = mesaj.get("message_id")
                        print(f"[YUKLE] Snap yüklendi")
                        return
                    except Exception as e:
                        print(f"[YUKLE PARSE HATA] {e}")
        print("[YUKLE] Snap bulunamadı, sıfırdan başlanıyor")
    except Exception as e:
        print(f"[YUKLE HATA] {e}")


def telegram_gonder(mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        if r.json().get("ok"):
            return r.json()["result"]["message_id"]
        else:
            print(f"Telegram hata: {r.json()}")
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
        veri = r.json()
        if not veri.get("ok"):
            print(f"Telegram düzenle hata: {veri.get('description')}")
            return False
        return True
    except Exception as e:
        print(f"Telegram düzenle hata: {e}")
        return False


def bot_calistir():
    global mesaj_id, son_guncelleme, son_kayit

    print("Paribu Takip Botu başlatılıyor...")
    yukle()

    while True:
        simdi = time.time()

        guncel = paribu_fiyatlar()
        if not guncel:
            time.sleep(VERI_SURESI)
            continue

        # Snap güncelle
        snap_guncelle(guncel, simdi)

        # Kaydet
        if simdi - son_kayit >= KAYIT_SURESI:
            kaydet()
            son_kayit = simdi

        # Telegram güncelle
        if simdi - son_guncelleme >= GUNCELLEME_SURESI:
            degisimler = degisim_hesapla(guncel, simdi)
            herhangi = any(len(v) > 0 for v in degisimler.values())

            if not herhangi:
                print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Veri toplanıyor...")
            else:
                mesaj = mesaj_olustur(degisimler, simdi)
                if mesaj_id is None:
                    mesaj_id = telegram_gonder(mesaj)
                    print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] İlk mesaj gönderildi!")
                else:
                    basari = telegram_duzenle(mesaj_id, mesaj)
                    if not basari:
                        mesaj_id = telegram_gonder(mesaj)
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Yeni mesaj gönderildi!")
                    else:
                        top = max(degisimler.get("20dk", [("?",0,0)]), key=lambda x: x[1])
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Güncellendi - Top: {top[0]} %{top[1]:.2f}")

            son_guncelleme = simdi

        time.sleep(VERI_SURESI)


if __name__ == "__main__":
    bot_calistir()
