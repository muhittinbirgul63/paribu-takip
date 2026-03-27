"""
Paribu Değişim Takip Botu
- Kayan pencere sistemi: her zaman tam 20dk, 1sa, 2sa öncesiyle karşılaştırır
- Mesaj güncellenir, yeni mesaj atılmaz
- Restart olunca Telegram'dan geçmiş okur
"""

import requests
import time
import os
import json
from datetime import datetime, timezone, timedelta
from collections import deque
from dotenv import load_dotenv

load_dotenv()

TZ_TR          = timezone(timedelta(hours=3))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")
ADMIN_ID       = str(os.getenv("ADMIN_ID", "1072335473"))

GUNCELLEME_SURESI = 4    # Telegram güncelleme (saniye)
VERI_SURESI       = 5    # Fiyat çekme (saniye)
KAYIT_SURESI      = 120  # Geçmiş kaydetme (saniye)

PERIYOTLAR = {"20dk": 1200, "1sa": 3600, "2sa": 7200}

# Her coin için zaman damgalı fiyat geçmişi
# { "BTC": deque([(zaman, fiyat), ...]) }
fiyat_gecmisi = {}
MAX_GECMIS    = 3000  # 2sa / 5sn = 1440, biraz fazla tutalım

mesaj_id       = None
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
    if fiyat >= 1000:   return f"{fiyat:,.2f}₺"
    elif fiyat >= 1:    return f"{fiyat:.3f}₺"
    elif fiyat >= 0.01: return f"{fiyat:.4f}₺"
    else:               return f"{fiyat:.6f}₺"


def gecmis_guncelle(guncel, simdi):
    """Her coin için geçmişe yeni fiyat ekle, çok eskiyi sil."""
    en_eski_tut = simdi - max(PERIYOTLAR.values()) - 60  # 2sa + 1dk tolerans

    for coin, fiyat in guncel.items():
        if coin not in fiyat_gecmisi:
            fiyat_gecmisi[coin] = deque(maxlen=MAX_GECMIS)
        fiyat_gecmisi[coin].append((simdi, fiyat))

        # 2 saatten eski kayıtları temizle
        while fiyat_gecmisi[coin] and fiyat_gecmisi[coin][0][0] < en_eski_tut:
            fiyat_gecmisi[coin].popleft()


def gecmisteki_fiyat(coin, simdi, periyot_sn):
    """
    Tam periyot_sn önce o coinin fiyatını bul.
    Hedef zamana en yakın kaydı döndür.
    """
    if coin not in fiyat_gecmisi or not fiyat_gecmisi[coin]:
        return None

    hedef_zaman = simdi - periyot_sn
    en_yakin_fiyat = None
    en_fark        = float("inf")

    for zaman, fiyat in fiyat_gecmisi[coin]:
        fark = abs(zaman - hedef_zaman)
        if fark < en_fark:
            en_fark        = fark
            en_yakin_fiyat = fiyat

    # Hedef zamana 60 saniyeden fazla uzaksa güvenilir değil
    if en_fark > 60:
        return None

    return en_yakin_fiyat


def degisim_hesapla(guncel, simdi, periyot_sn):
    """Tüm coinler için kayan pencere değişimini hesapla."""
    degisimler = []
    for coin, guncel_fiyat in guncel.items():
        eski_fiyat = gecmisteki_fiyat(coin, simdi, periyot_sn)
        if eski_fiyat is None or eski_fiyat <= 0:
            continue
        degisim = ((guncel_fiyat - eski_fiyat) / eski_fiyat) * 100
        degisimler.append((coin, degisim, guncel_fiyat))

    degisimler.sort(key=lambda x: x[1], reverse=True)
    return degisimler


def mesaj_olustur(guncel, simdi):
    zaman     = datetime.now(TZ_TR).strftime("%H:%M:%S")
    bolumler  = []
    etiketler = {"20dk": "20 Dakika", "1sa": "1 Saat", "2sa": "2 Saat"}
    emojiler  = {"20dk": "🏃", "1sa": "⏰", "2sa": "🕰"}

    for periyot, periyot_sn in PERIYOTLAR.items():
        degisimler = degisim_hesapla(guncel, simdi, periyot_sn)
        if not degisimler:
            continue

        satirlar = [
            f"{emojiler[periyot]} <b>Paribu Yükselenler</b>",
            f"🕐 <i>Son {etiketler[periyot]}</i>",
            "",
        ]
        for coin, deg, fiyat in degisimler[:7]:
            isaret = "+" if deg >= 0 else ""
            satirlar.append(
                f"🟢 <b>{coin}/TL</b>  <code>{isaret}{deg:.2f}%</code>  <i>{fiyat_formatla(fiyat)}</i>"
            )
        bolumler.append("\n".join(satirlar))

    if not bolumler:
        return None

    return "\n─────────────────────\n".join(bolumler) + f"\n<i>🔄 {zaman}</i>"


def telegram_gonder(mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        veri = r.json()
        if veri.get("ok"):
            return veri["result"]["message_id"]
        print(f"[GONDER HATA] {veri.get('description')}")
    except Exception as e:
        print(f"[GONDER HATA] {e}")
    return None


def telegram_duzenle(msg_id, mesaj):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": CHAT_ID, "message_id": msg_id, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        veri = r.json()
        if veri.get("ok"):
            return True
        if "not modified" in veri.get("description", ""):
            return True
        print(f"[DUZENLE HATA] {veri.get('description')}")
        return False
    except Exception as e:
        print(f"[DUZENLE HATA] {e}")
        return False


def kaydet():
    """Fiyat geçmişini ve mesaj_id'yi Telegram'a kaydet."""
    global kayit_mesaj_id
    try:
        gecmis_ozet = {}
        for coin, dq in list(fiyat_gecmisi.items())[:150]:
            gecmis_ozet[coin] = list(dq)[-100:]

        veri  = {"mesaj_id": mesaj_id, "gecmis": gecmis_ozet}
        metin = f"PARIBU_SNAP:{json.dumps(veri)}"

        # Telegram 4096 karakter limiti — aşarsa kısalt
        if len(metin) > 4000:
            gecmis_ozet2 = {}
            for coin, dq in list(fiyat_gecmisi.items())[:80]:
                gecmis_ozet2[coin] = list(dq)[-50:]
            veri  = {"mesaj_id": mesaj_id, "gecmis": gecmis_ozet2}
            metin = f"PARIBU_SNAP:{json.dumps(veri)}"

        if kayit_mesaj_id is None:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": metin},
                timeout=10
            )
            if r.json().get("ok"):
                kayit_mesaj_id = r.json()["result"]["message_id"]
                print("[KAYIT] İlk kayıt yapıldı")
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={"chat_id": ADMIN_ID, "message_id": kayit_mesaj_id, "text": metin},
                timeout=10
            )
            if r.json().get("ok"):
                print("[KAYIT] Güncellendi")
    except Exception as e:
        print(f"[KAYIT HATA] {e}")


def yukle():
    """Telegram'dan kaydedilmiş geçmişi oku."""
    global kayit_mesaj_id, mesaj_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100}, timeout=10
        )
        for item in reversed(r.json().get("result", [])):
            m = item.get("message", {})
            if str(m.get("chat", {}).get("id", "")) == ADMIN_ID:
                metin = m.get("text", "")
                if metin.startswith("PARIBU_SNAP:"):
                    try:
                        veri = json.loads(metin[12:])
                        mesaj_id       = veri.get("mesaj_id")
                        kayit_mesaj_id = m.get("message_id")

                        for coin, kayitlar in veri.get("gecmis", {}).items():
                            fiyat_gecmisi[coin] = deque(
                                [tuple(k) for k in kayitlar], maxlen=MAX_GECMIS
                            )

                        print(f"[YUKLE] Yüklendi, mesaj_id={mesaj_id}, {len(fiyat_gecmisi)} coin")
                        return
                    except Exception as e:
                        print(f"[YUKLE PARSE HATA] {e}")
        print("[YUKLE] Geçmiş bulunamadı, sıfırdan başlıyor")
    except Exception as e:
        print(f"[YUKLE HATA] {e}")


def bot_calistir():
    global mesaj_id, son_guncelleme, son_kayit

    print("Paribu Takip Botu başlatılıyor...")
    yukle()

    while True:
        try:
            simdi = time.time()

            guncel = paribu_fiyatlar()
            if not guncel:
                time.sleep(VERI_SURESI)
                continue

            # Geçmişe ekle
            gecmis_guncelle(guncel, simdi)

            # Geçmişi kaydet
            if simdi - son_kayit >= KAYIT_SURESI:
                kaydet()
                son_kayit = simdi

            # Telegram güncelle
            if simdi - son_guncelleme >= GUNCELLEME_SURESI:
                mesaj = mesaj_olustur(guncel, simdi)

                if mesaj is None:
                    print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Veri toplanıyor...")
                elif mesaj_id is None:
                    mesaj_id = telegram_gonder(mesaj)
                    if mesaj_id:
                        kaydet()
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] İlk mesaj gönderildi!")
                else:
                    basari = telegram_duzenle(mesaj_id, mesaj)
                    if basari:
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Güncellendi")
                    else:
                        print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Yeni mesaj gönderiliyor")
                        mesaj_id = telegram_gonder(mesaj)
                        if mesaj_id:
                            kaydet()

                son_guncelleme = simdi

        except Exception as e:
            print(f"[ANA DÖNGÜ HATA] {e}")
            time.sleep(10)

        time.sleep(VERI_SURESI)


if __name__ == "__main__":
    bot_calistir()
