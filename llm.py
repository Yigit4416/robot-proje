import os
from google import genai
from dotenv import load_dotenv

# .env dosyasındaki değişkenleri environment variables olarak yükler
load_dotenv()

# .env dosyanın içinde anahtarın ismine göre burayı ayarla.
# Eğer .env içinde GOOGLE_API_KEY=... yazdıysan, kütüphane bunu otomatik bulur.
# Eğer anahtarın ismi farklıysa (örneğin GEMINI_API_KEY), manuel belirtmen gerekir:
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Hata: .env dosyasında GOOGLE_API_KEY veya GEMINI_API_KEY bulunamadı!")
else:
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Explain how AI works in a few words"
        )
        print("Yanıt:")
        print(response.text)
    except Exception as e:
        print(f"Bir hata oluştu: {e}")