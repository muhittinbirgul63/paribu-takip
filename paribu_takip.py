"""
Paribu 1 Saatlik Değişim Takip Botu
- Her 5 saniyede Paribu ask fiyatlarını çeker
- Başlangıç fiyatıyla karşılaştırır (1 saate kadar büyür)
- Top 10 yükselen coini Telegram'da canlı günceller
"""

import requests
import time
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# {coin: ask_fiyat} - 1 saat önce kaydedilen fiyatlar
baslangic_fiyatlar = {}
baslangic_zamani = {}

mesaj_id = None
son_guncelleme = 0
GUNCELLEME_SURESI = 10
VERI_SURESI = 5
GECMIS_SURE = 3600


def paribu_ask_fiyatlar():
    try:
        r = requests.get("https://www.paribu.com/ticker", timeout=10)
        sonuc = {}
        for parite, bilgi in r.json().items():
            if "_TL" in parite.upper():
                coin = parite.upper().replace("_TL", "")
                bid = float(bilgi.get("highestBid", 0))
                if bid > 0:
                    sonuc[coin] = bid
        return sonuc
    except Exception as e:
        print(f"Paribu hata: {e}")
        return {}


def fiyat_formatla(fiyat):
    if fiyat >= 1000:
        return f"{fiyat:,.2f}₺"
    elif fiyat >= 1:
        return f"{fiyat:.3f}₺"
    elif fiyat >= 0.01:
        return f"{fiyat:.4f}₺"
    else:
        return f"{fiyat:.6f}₺"


def mesaj_olustur(degisimler, gecen_sure):
    zaman = datetime.now().strftime("%H:%M:%S")
    dk = int(gecen_sure // 60)
    sn = int(gecen_sure % 60)
    sure_str = f"{dk}dk {sn}sn" if dk > 0 else f"{sn}sn"

    satirlar = [
        f"📊 <b>Paribu Yükselenler</b>",
        f"🕐 <i>Son {sure_str}</i>",
        "",
    ]

    for i, (coin, degisim, ask) in enumerate(degisimler[:10]):
        isaret = "+" if degisim >= 0 else ""
    for i, (coin, degisim, ask) in enumerate(degisimler[:10]):
        isaret = "+" if degisim >= 0 else ""
        satirlar.append("🟢 <b>" + coin + "/TL</b>")
        satirlar.append("   <code>" + isaret + f"{degisim:.2f}%</code>  ›  <b>" + fiyat_formatla(ask) + "</b>")
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
        veri = r.json()
        if veri.get("ok"):
            return veri["result"]["message_id"]
        else:
            print(f"Telegram hata: {veri}")
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
    global mesaj_id, baslangic_fiyatlar, baslangic_zamani, son_guncelleme

    print("Paribu Takip Botu başlatılıyor...")

    while True:
        simdi = time.time()

        # Güncel fiyatları çek
        guncel = paribu_ask_fiyatlar()
        if not guncel:
            time.sleep(VERI_SURESI)
            continue

        # Başlangıç fiyatlarını kaydet
        for coin, ask in guncel.items():
            if coin not in baslangic_fiyatlar:
                baslangic_fiyatlar[coin] = ask
                baslangic_zamani[coin] = simdi

        # 1 saatten eski başlangıç fiyatlarını güncelle
        for coin in list(baslangic_fiyatlar.keys()):
            if simdi - baslangic_zamani[coin] > GECMIS_SURE:
                if coin in guncel:
                    baslangic_fiyatlar[coin] = guncel[coin]
                    baslangic_zamani[coin] = simdi

        # Telegram güncelleme
        if simdi - son_guncelleme >= GUNCELLEME_SURESI:
            degisimler = []
            for coin, guncel_ask in guncel.items():
                if coin not in baslangic_fiyatlar:
                    continue
                eski_ask = baslangic_fiyatlar[coin]
                gecen = simdi - baslangic_zamani[coin]
                if gecen < 5 or eski_ask <= 0:
                    continue
                degisim = ((guncel_ask - eski_ask) / eski_ask) * 100
                degisimler.append((coin, degisim, guncel_ask))

            degisimler.sort(key=lambda x: x[1], reverse=True)

            if not degisimler:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Veri bekleniyor...")
            else:
                gecen_sure = simdi - min(baslangic_zamani.values())
                mesaj = mesaj_olustur(degisimler, gecen_sure)
                if mesaj_id is None:
                    mesaj_id = telegram_gonder(mesaj)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] İlk mesaj gönderildi!")
                else:
                    telegram_duzenle(mesaj_id, mesaj)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Güncellendi - Top: {degisimler[0][0]} %{degisimler[0][1]:.2f}")

            son_guncelleme = simdi

        time.sleep(VERI_SURESI)


if __name__ == "__main__":
    bot_calistir()
