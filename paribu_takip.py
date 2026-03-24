"""
Paribu 1 Saatlik Değişim Takip Botu
- Her 5 saniyede Paribu highestBid fiyatlarını çeker
- Gerçek 1 saatlik değişimi gösterir
- Restart olunca Telegram'dan fiyat geçmişini okur
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
ADMIN_ID       = os.getenv("ADMIN_ID", "1072335473")

GUNCELLEME_SURESI = 10    # Telegram güncelleme (saniye)
VERI_SURESI       = 5     # Fiyat çekme (saniye)
GECMIS_SURE       = 3600  # 1 saat
KAYIT_SURESI      = 300   # 5 dakikada bir geçmiş kaydet

# Fiyat geçmişi: {coin: [(timestamp, bid), ...]}
fiyat_gecmisi = {}

mesaj_id       = None
kayit_mesaj_id = None  # Geçmişi saklayan gizli mesaj
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


def gecmis_kaydet():
    """Fiyat geçmişini Telegram'a kaydet"""
    global kayit_mesaj_id
    try:
        # Sadece son 1 saatlik veriyi kaydet
        simdi = time.time()
        kayit = {}
        for coin, kayitlar in fiyat_gecmisi.items():
            son_1saat = [(t, f) for t, f in kayitlar if simdi - t <= GECMIS_SURE + 60]
            if son_1saat:
                kayit[coin] = son_1saat[-1]  # En son fiyat ve zaman

        veri = json.dumps(kayit)
        mesaj = f"<code>PARIBU_GECMIS:{veri}</code>"

        if kayit_mesaj_id is None:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": mesaj, "parse_mode": "HTML"},
                timeout=10
            )
            if r.json().get("ok"):
                kayit_mesaj_id = r.json()["result"]["message_id"]
                print(f"[KAYIT] Geçmiş kaydedildi (yeni mesaj: {kayit_mesaj_id})")
        else:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={"chat_id": ADMIN_ID, "message_id": kayit_mesaj_id, "text": mesaj, "parse_mode": "HTML"},
                timeout=10
            )
            print(f"[KAYIT] Geçmiş güncellendi")
    except Exception as e:
        print(f"[KAYIT HATA] {e}")


def gecmis_yukle():
    """Telegram'dan fiyat geçmişini yükle"""
    global kayit_mesaj_id
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100},
            timeout=10
        )
        # Son mesajları tara
        for item in reversed(r.json().get("result", [])):
            mesaj = item.get("message", {})
            if str(mesaj.get("chat", {}).get("id", "")) == str(ADMIN_ID):
                metin = mesaj.get("text", "")
                if "PARIBU_GECMIS:" in metin:
                    try:
                        veri_str = metin.split("PARIBU_GECMIS:")[1].rstrip("</code>").strip()
                        kayit = json.loads(veri_str)
                        simdi = time.time()
                        yuklu = 0
                        for coin, (t, f) in kayit.items():
                            if simdi - t <= GECMIS_SURE + 60:
                                fiyat_gecmisi[coin] = [(t, f)]
                                yuklu += 1
                        kayit_mesaj_id = mesaj.get("message_id")
                        print(f"[YUKLE] {yuklu} coin geçmişi yüklendi")
                        return
                    except: pass
        print("[YUKLE] Geçmiş bulunamadı, sıfırdan başlanıyor")
    except Exception as e:
        print(f"[YUKLE HATA] {e}")


def degisim_hesapla(guncel, simdi):
    degisimler = []
    for coin, guncel_bid in guncel.items():
        gecmis = fiyat_gecmisi.get(coin, [])
        if len(gecmis) < 2:
            continue
        eski_zaman, eski_bid = gecmis[0]
        gecen = simdi - eski_zaman
        if gecen < 10 or eski_bid <= 0:
            continue
        degisim = ((guncel_bid - eski_bid) / eski_bid) * 100
        degisimler.append((coin, degisim, guncel_bid, gecen))
    degisimler.sort(key=lambda x: x[1], reverse=True)
    return degisimler


def mesaj_olustur(degisimler):
    zaman = datetime.now(TZ_TR).strftime("%H:%M:%S")

    if degisimler:
        gecen = degisimler[0][3]
        sa  = int(gecen // 3600)
        dk  = int((gecen % 3600) // 60)
        sn  = int(gecen % 60)
        if sa > 0:
            sure_str = f"{sa}sa {dk}dk"
        elif dk > 0:
            sure_str = f"{dk}dk {sn}sn"
        else:
            sure_str = f"{sn}sn"
    else:
        sure_str = "?"

    satirlar = [
        f"📊 <b>Paribu Yükselenler</b>",
        f"🕐 <i>Son {sure_str}</i>",
        "",
    ]

    for coin, degisim, bid, _ in degisimler[:10]:
        isaret = "+" if degisim >= 0 else ""
        satirlar.append("🟢 <b>" + coin + "/TL</b>")
        satirlar.append("   <code>" + isaret + f"{degisim:.2f}%</code>  ›  <b>" + fiyat_formatla(bid) + "</b>")
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
    except Exception as e:
        print(f"Telegram gönder hata: {e}")
    return None


def telegram_duzenle(msg_id, mesaj):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": CHAT_ID, "message_id": msg_id, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram düzenle hata: {e}")


def bot_calistir():
    global mesaj_id, son_guncelleme, son_kayit

    print("Paribu Takip Botu başlatılıyor...")

    # Geçmişi yükle
    gecmis_yukle()

    while True:
        simdi = time.time()

        # Fiyatları çek
        guncel = paribu_fiyatlar()
        if not guncel:
            time.sleep(VERI_SURESI)
            continue

        # Geçmişe ekle
        for coin, bid in guncel.items():
            if coin not in fiyat_gecmisi:
                fiyat_gecmisi[coin] = []
            fiyat_gecmisi[coin].append((simdi, bid))
            # 1 saatten eski sil
            fiyat_gecmisi[coin] = [(t, f) for t, f in fiyat_gecmisi[coin] if simdi - t <= GECMIS_SURE + 60]

        # Geçmişi kaydet
        if simdi - son_kayit >= KAYIT_SURESI:
            gecmis_kaydet()
            son_kayit = simdi

        # Telegram güncelle
        if simdi - son_guncelleme >= GUNCELLEME_SURESI:
            degisimler = degisim_hesapla(guncel, simdi)

            if not degisimler:
                print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Veri toplanıyor...")
            else:
                mesaj = mesaj_olustur(degisimler)
                if mesaj_id is None:
                    mesaj_id = telegram_gonder(mesaj)
                    print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] İlk mesaj gönderildi!")
                else:
                    telegram_duzenle(mesaj_id, mesaj)
                    print(f"[{datetime.now(TZ_TR).strftime('%H:%M:%S')}] Güncellendi - Top: {degisimler[0][0]} %{degisimler[0][1]:.2f}")

            son_guncelleme = simdi

        time.sleep(VERI_SURESI)


if __name__ == "__main__":
    bot_calistir()
