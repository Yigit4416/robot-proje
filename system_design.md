# System Architecture - Dual Cluster & Priority Logic

## 1. Mimari Akış Şeması (Flowchart)

Bu şema, sistemin engelleri algıladıktan sonra nasıl iki farklı kümeye (Cluster) dağıttığını ve öncelik yönetimini gösterir.

```mermaid
graph TD
    %% Nodes
    Sensor([📷 Robot Sensör Verisi])
    DistCheck{Mesafe Kontrolü}
    
    %% Cluster A Group
    subgraph ClusterA [Cluster A: Yakın Mesafe / Öncelikli]
        direction TB
        LB((⚖️ Yük Dengeleyici))
        M1[⚡ ministral-3:3b]
        M2[🧠 qwen2.5:1.5b]
        
        LB -->|En Hızlı| M1
        LB -->|Alternatif| M2
    end
    
    %% Cluster B Group
    subgraph ClusterB [Cluster B: Uzak Mesafe / Arka Plan]
        direction TB
        DS[🤔 deepseek-r1:1.5b]
        Reason[Mantıksal Çıkarım]
        
        DS --- Reason
    end
    
    %% Decision & Pathfinding
    RiskScore[📊 Risk Skoru (0-100)]
    AStar[📍 Weighted A* Rota Planlama]
    
    %% Flow Connections
    Sensor --> DistCheck
    
    %% Paths
    DistCheck -->|"< 2 Blok (Yakın)"| LB
    DistCheck -->|">= 2 Blok (Uzak)"| DS
    
    %% Outputs
    M1 --> RiskScore
    M2 --> RiskScore
    DS --> RiskScore
    
    RiskScore --> AStar
    
    %% Priority Upgrade Link
    DS -.->|⚠️ Robot Yaklaşırsa! (Priority Upgrade)| LB
    
    %% Styling
    style Sensor fill:#f9f,stroke:#333,stroke-width:2px
    style ClusterA fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style ClusterB fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style RiskScore fill:#fff9c4,stroke:#fbc02d,stroke-width:2px
    style AStar fill:#ffe0b2,stroke:#f57c00,stroke-width:2px
    
    linkStyle 6 stroke:red,stroke-width:3px,stroke-dasharray: 5 5;
```

## 2. Sıralı İşleyiş Diyagramı (Sequence Diagram)

```mermaid
sequenceDiagram
    participant Robot as 🤖 Robot
    participant Cache as 💾 Cache
    participant CA as ⚡ Cluster A (Hızlı)
    participant CB as 🤔 Cluster B (Akılcı)
    
    Robot->>Robot: Engel Tespit (Obj_123)
    Robot->>Cache: Bilinen Engel mi?
    
    alt Evet (Cache Hit)
        Cache-->>Robot: Skor: 40 (Anlık)
    else Hayır (Cache Miss)
        Robot->>Robot: Mesafe Analizi
        
        alt Mesafe < 2 (Kritik)
            Robot->>CA: Analiz İsteği
            activate CA
            Note right of Robot: HIZ: 0.1x (Yavaşla)
            CA-->>Robot: Skor: 85 (Duvar)
            deactivate CA
        else Mesafe >= 2 (Güvenli)
            Robot->>CB: Analiz İsteği
            activate CB
            Note right of Robot: HIZ: 1.0x (Tam Gaz)
            
            opt Robot Yaklaşırsa (<2)
                Robot->>CB: İPTAL ET
                deactivate CB
                Robot->>CA: ACİL ANALİZ (Upgrade)
                activate CA
                Note right of Robot: HIZ: 0.1x (Fren)
                CA-->>Robot: Skor: 85
                deactivate CA
            end
            
            CB-->>Robot: Skor: 20 (Güvenli)
            deactivate CB
        end
        
        Robot->>Cache: Kaydet (Obj_Tipi -> Skor)
    end
```

## 3. Sistem Bileşenleri ve Rolleri

### 📷 Sensör Katmanı (Sensor Layer)
- **Görev:** Haritadaki nesneleri ve özelliklerini (tip, görsel, fizik) algılar.
- **Mantık:** Robotun görüş alanındaki (Line of Sight) nesneleri `map_visualization.py` içindeki `check_sensors()` fonksiyonu ile tarar.

### 🧠 Karar Kümeleri (Dual Clusters)
Sistem, yük dengeleme ve önceliklendirme için iki farklı model kümesi kullanır:

#### Cluster A (Yakın Mesafe / Kritik)
- **Modeller:** `ministral-3:3b` ve `qwen2.5:1.5b`.
- **Kullanım:** Robota 2 bloktan daha **yakın** olan engeller için kullanılır.
- **Özellik:** Hızlı yanıt süresi ve yük dengeleme (Load Balancing) ile çalışır. Araba bu analizler sırasında yavaşlar (0.1x hız).

#### Cluster B (Uzak Mesafe / Arka Plan)
- **Modeller:** `deepseek-r1:1.5b`.
- **Kullanım:** Robota 2 blok veya daha **uzak** olan engeller için kullanılır.
- **Özellik:** Arka planda çalışır, robotun hızını kesmez. Eğer robot bu nesnelere yaklaşırsa (Dist < 2), görev otomatik olarak iptal edilip Cluster A'ya (Öncelikli) aktarılır.

### 💾 Karar Önbelleği (Decision Cache)
- **Görev:** Daha önce analiz edilmiş nesne tiplerini (örn: "puddle") hatırlar.
- **Fayda:** Aynı tür engeller için tekrar tekrar LLM çağrısı yapılmasını engeller, performansı artırır.

## 4. Operasyonel Mantık

### Hız Kontrolü (Adaptive Speed Control)
- **Normal (1.0x):** Sadece Cluster B (Uzak) analizleri kuyruktayken veya kuyruk boşken.
- **Yavaş (0.1x):** Cluster A (Yakın) analizleri devreye girdiğinde veya "Priority Upgrade" gerçekleştiğinde robot güvenli analiz için yavaşlar.
- **Warmup:** Başlangıçta modeller belleğe yüklenirken robot 0.0x hızında bekler.

### Yük Dengeleme (Load Balancing)
`OllamaAnalyzer` sınıfı, Cluster A içinde model seçerken şu algoritmayı izler:
1. **Boş Model:** Kuyruğu boş olan modeli seçer.
2. **En Hızlı:** Eğer ikisi de boşsa, ortalama yanıt süresi (Avg Time) en düşük olanı seçer.
3. **En Az Yüklü:** Eğer ikisi de doluysa, kuyruk uzunluğu en az olanı seçer.
