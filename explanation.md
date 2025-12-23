# Otonom Robot A* Simülasyonu - Proje Raporu

Bu proje, bilinmeyen bir ortamda hareket eden otonom bir robotun, engelleri sensörleri yardımıyla keşfederek hedefe en kısa yoldan ulaşmasını simüle eden bir Python uygulamasıdır.

## 1. Proje Özeti
Simülasyon, ızgara tabanlı (grid-based) bir harita üzerinde çalışır. Robot, başlangıç noktasından (Start) bitiş noktasına (End) gitmeye çalışır. Harita üzerinde "sabit duvarlar" ve rastgele yerleştirilmiş "gizli engeller" bulunur. Robot, başlangıçta sadece kendi konumunu ve sabit duvarları bilir; gizli engelleri ise sensör menziline girdiğinde keşfeder.

## 2. Temel Özellikler

### A* (A-Star) Algoritması
Robotun yol bulma mekanizması **A*** algoritmasına dayanır. A*, başlangıçtan hedefe olan en düşük maliyetli yolu bulmak için hem kat edilen mesafeyi (g-score) hem de hedefe kalan tahmini mesafeyi (h-score / heuristic) kullanır. Bu projede Heuristic fonksiyonu olarak **Manhattan Mesafesi** (`|x1-x2| + |y1-y2|`) kullanılmıştır.

### Dinamik Rota Planlama (Replanning)
Robot hareket halindeyken, başlangıçta hesapladığı rotanın geçerliliğini sürekli kontrol eder ve gerektiğinde rotayı yeniden hesaplar (`recalculate_path`). Bu işlem şu üç temel durumda tetiklenir:

1.  **Sensör Taraması Sonrasında:** Robot çevresini taradığında (`check_sensors`), eğer yeni keşfettiği bir engel (daha önce bilinmeyen 'gizli engel') **mevcut planlanan rotasının üzerindeyse**, yol tıkandığı için hemen yeni bir rota hesaplanır.
2.  **Çarpışma Kontrolü Anında:** Robot bir sonraki kareye hareket etmek üzereyken (`move_car`), sensörden kaçan ancak fiziksel olarak orada olan bir engelle karşılaşırsa (duvara çarpma durumu), bu konumu engel olarak işaretler ve rotayı günceller.
3.  **Kullanıcı Müdahalesi:** Kullanıcı simülasyon sırasında mouse ile haritaya yeni bir duvar eklediğinde, eğer bu yeni duvar robotun yolu üzerindeyse rota anında yeniden hesaplanır.

### Sensör ve Görüş Hattı (Line of Sight)
Robotun çevresini algılaması iki kurala bağlıdır:
1.  **Menzil (Range):** Robot sadece belirli bir yakınlıktaki (Manhattan mesafesi <= 4 birim) kareleri tarayabilir.
2.  **Görüş Hattı (Line of Sight - LOS):** Robot, aradaki engellerin arkasını göremez. Sensör verisi almak istediği kare ile kendi arasında bir duvar veya engel varsa, o karedeki bilgiye erişemez. Bu özellik, **Bresenham Çizgi Algoritması** (Raycasting) ile simüle edilmiştir.

## 3. Kod Yapısı ve İşleyiş (`map_visualization.py`)

Proje temel olarak `PathfindingVisualizer` sınıfı üzerinden yürütülür.

*   **Harita Yapısı (`real_map` vs `known_map`):**
    *   `real_map`: Gerçek dünyayı temsil eder. Tüm duvarları ve gizli engelleri içerir (Ground Truth).
    *   `known_map`: Robotun hafızasını temsil eder. Başlangıçta sadece sabit duvarları bilir. Keşfettikçe güncellenir. A* algoritması *sadece* bu haritayı kullanır.

*   **`find_path_astar()`:** `known_map` üzerindeki veriyi kullanarak en kısa yolu hesaplar.
*   **`check_sensors()`:** Robotun etrafını tarar. Eğer bir kare menzil içindeyse VE görüş hattı (Line of Sight) açıksa, o karedeki gizli engeli `known_map`'e işler.
*   **`has_line_of_sight(start, end)`:** Robotun bulunduğu kare ile hedef kare arasına sanal bir çizgi çeker. Eğer çizgi üzerinde (başlangıç ve bitiş hariç) dolu bir kare varsa `False`, yoksa `True` döner.
*   **Görselleştirme (Pygame):**
    *   **Gri Kareler:** Henüz keşfedilmemiş alanlar veya boş yollar.
    *   **Kırmızı:** Engeller (Duvarlar).
    *   **Yeşil:** Hesaplanan rota.
    *   **Mavi:** Robot.
    *   **Sarı Çerçeve:** Sensör menzili.

### Semantik Engel Analizi ve LLM Entegrasyonu (Yeni)
Simülasyon, engelleri sadece "geçilmez bloklar" olarak değil, farklı zorluk derecelerine sahip "semantik objeler" olarak değerlendirir.

1.  **Semantik Analiz:** Robot bir engel keşfettiğinde (örn: su birikintisi, çamur), bu engelin fiziksel özelliklerini analiz eder ve LLM'e (Büyük Dil Modeli) bir risk skoru (0-100) danışır.
2.  **Ağırlıklı A* (Weighted A*):** Geleneksel A*'ın aksine, her kare 1 maliyetinde değildir. LLM'den gelen skor, karenin geçiş maliyetini etkiler: `Maliyet = 1 + (Skor / 10)`. Robot, eğer etraftan dolaşmak "çamurun içinden geçmekten" daha maliyetliyse, engelin içinden geçmeyi tercih edebilir.
3.  **Karar Önbellekleme (Decision Caching):** LLM sorguları zaman alabileceği için robot daha önce analiz ettiği engel tiplerini hafızasına kaydeder. Aynı tip engelle tekrar karşılaştığında saniyeler içinde karar verir ve akıcılığı korur.
4.  **Adaptif Hız Kontrolü:** Karar verme süreci uzarsa (LLM bekleme süresi > 0.5s), robot güvenli geçiş için yavaşlar veya tamamen durur.

#### Loglama (`log_encounter` & `LLM` logs):
Robot yeni bir engel keşfettiğinde veya LLM'den cevap geldiğinde terminale detaylı bilgi basılır:
*   `[LLM] Evaluation complete for obj_123. Verdict: Score 40`
*   `[CACHE] Saved puddle -> 40`

## 4. Kullanım

Simülasyon başlatıldığında robot otomatik olarak hedefe gitmeye başlar.
*   **[SPACE]**: Simülasyonu Durdur/Devam Ettir.
*   **[R]**: Simülasyonu sıfırla (Yeni rastgele engeller oluşturur).
*   **Mouse Sol Tık**: Haritaya canlı olarak yeni duvar eklemenizi sağlar (Robot bunu anında fark edip yolunu değiştirebilir).

## 5. Sonuç
Bu simülasyon, robotik ve oyun programlamada sıklıkla karşılaşılan "Bilinmeyen Ortamda Gezinme" (Navigation in Unknown Environments) probleminin temel bir örneğidir. Görüş hattı kısıtlamasının eklenmesiyle simülasyon daha gerçekçi bir hale getirilmiş, robotun sadece "görebildiği" engellere tepki vermesi sağlanmıştır.
