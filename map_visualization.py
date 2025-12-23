import pygame
import sys
import heapq
import random
import time
import math
import threading
import datetime
from ollama import OllamaAnalyzer

# --- AYARLAR (CONSTANTS) ---
CELL_SIZE = 10
MAP_WIDTH = 80
MAP_HEIGHT = 60
WINDOW_WIDTH = MAP_WIDTH * CELL_SIZE
WINDOW_HEIGHT = MAP_HEIGHT * CELL_SIZE
FPS = 10  # Reduced speed for visibility

# Renkler (R, G, B)
COLOR_BG = (20, 20, 20)
COLOR_GRID = (40, 40, 40)
COLOR_WALL = (200, 50, 50)        # Sabit duvarlar
COLOR_PATH = (0, 200, 0)
COLOR_CAR = (50, 150, 255)
COLOR_SENSOR = (255, 255, 0)
COLOR_START = (0, 255, 127)
COLOR_END = (255, 0, 127)
COLOR_TEXT = (220, 220, 220)

# Map kodları:
# real_map: 0 boş, 1 sabit duvar, 2 gizli engel (ground truth)
# known_map: 0 bilinmiyor/boş sanıyor, 1 bilinen engel (duvar veya keşfedilen)

class PathfindingVisualizer:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("Bilinmeyen Ortamda Otonom Robot Navigasyonu")
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("consolas", 16)

        self.running = True
        self.paused = False
        
        # LLM Integration
        self.analyzer = OllamaAnalyzer()
        self.llm_results = [] # Thread-safe results queue
        self.llm_lock = threading.Lock()
        
        # LLM Simulation State (Now used for tracking real threads)
        self.llm_queue = []  # List of {start_time, thread, props}
        self.speed_modifier = 1.0  # 1.0=Full, 0.5=Half, 0.0=Stop

        self.real_map = []
        self.known_map = []
        
        # Karar Önbellekleme (Decision Caching)
        self.decision_cache = {} # type_name -> score
        self.cache_hit_count = 0
        self.processed_cache_ids = set()

        self.start_pos = (2, 2)
        self.end_pos = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
        self.car_pos = self.start_pos
        self.path = []

        # İstatistikler (sunumda çok iyi durur)
        self.steps = 0
        self.replans = 0
        self.discovered_obstacles = 0

        self.initialize_game()

    def create_grid(self, default=0):
        return [[default for _ in range(MAP_HEIGHT)] for _ in range(MAP_WIDTH)]

    def initialize_game(self):
        self.real_map = self.create_grid(0)
        self.known_map = self.create_grid(0)
        
        # Keşfedilen engellerin özellikleri (x, y) -> { "color": ... }
        self.obstacle_props = {} 

        self.car_pos = self.start_pos
        self.path = []

        self.steps = 0
        self.replans = 0
        self.discovered_obstacles = 0

        # Sabit duvarlar (bilinen)
        self.add_wall_line((20, 0), (20, 40))
        self.add_wall_line((50, 20), (50, 59))
        self.add_wall_line((20, 40), (40, 40))

        # Rastgele gizli engeller (real_map'te var, known_map'te yok)
        print("Rastgele gizli engeller oluşturuluyor...")
        for _ in range(300):
            rx = random.randint(0, MAP_WIDTH - 1)
            ry = random.randint(0, MAP_HEIGHT - 1)

            # Başlangıç ve bitişi kapatma
            if self.heuristic((rx, ry), self.start_pos) > 5 and \
               self.heuristic((rx, ry), self.end_pos) > 5 and \
               self.real_map[rx][ry] == 0:
                self.real_map[rx][ry] = 2

        self.recalculate_path(initial=True)
        self.game_start_time = time.time()

    def add_wall_line(self, start, end):
        x1, y1 = start
        x2, y2 = end

        if x1 == x2:  # Dikey
            for y in range(min(y1, y2), max(y1, y2) + 1):
                if 0 <= x1 < MAP_WIDTH and 0 <= y < MAP_HEIGHT:
                    self.real_map[x1][y] = 1
                    self.known_map[x1][y] = 1
        elif y1 == y2:  # Yatay
            for x in range(min(x1, x2), max(x1, x2) + 1):
                if 0 <= x < MAP_WIDTH and 0 <= y1 < MAP_HEIGHT:
                    self.real_map[x][y1] = 1
                    self.known_map[x][y1] = 1

    def heuristic(self, a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path_astar(self):
        start = self.car_pos
        end = self.end_pos

        queue = [(0, start)]
        g_score = {start: 0}
        came_from = {start: None}

        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

        while queue:
            current_f, current = heapq.heappop(queue)

            if current == end:
                path = []
                while current is not None:
                    path.append(current)
                    current = came_from[current]
                return path[::-1]

            cx, cy = current

            for dx, dy in directions:
                nx, ny = cx + dx, cy + dy

                if 0 <= nx < MAP_WIDTH and 0 <= ny < MAP_HEIGHT:
                    # Engel kontrolü (sadece known_map'e göre!)
                    # 1 = Kesin Duvar
                    if self.known_map[nx][ny] == 1:
                        continue
                    
                    # Semantik Maliyet Hesaplama
                    cell_cost = 1
                    if (nx, ny) in self.obstacle_props:
                        props = self.obstacle_props[(nx, ny)]
                        score = props.get("score", 0)
                        
                        # Score > 80 ise burayı duvar gibi gör (sonsuz maliyet)
                        if score > 80:
                            continue
                        
                        # Ağırlıklı Maliyet: 1 + (Score / 10)
                        # Örn: Mud (60) -> 7, Puddle (40) -> 5
                        cell_cost = 1 + (score / 10)
                    
                    # Eğer LLM henüz cevap vermediyse ve cache'de yoksa, 
                    # araba burayı geçici olarak "duvar" (riskli) görebilir.
                    # Ancak biz şimdilik sadece 'bilinen' skorları uyguluyoruz.

                    new_g = g_score[current] + cell_cost
                    if new_g < g_score.get((nx, ny), float("inf")):
                        came_from[(nx, ny)] = current
                        g_score[(nx, ny)] = new_g
                        f_score = new_g + self.heuristic((nx, ny), end)
                        heapq.heappush(queue, (f_score, (nx, ny)))

        return []

    def recalculate_path(self, initial=False):
        self.path = self.find_path_astar()
        if not initial:
            self.replans += 1
        if not self.path:
            print("Yol tıkandı veya bulunamadı!")

    def has_line_of_sight(self, start, end):
        """Bresenham's Line Algorithm ile görüş hattı kontrolü."""
        x0, y0 = start
        x1, y1 = end
        
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        x, y = x0, y0
        
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        
        err = dx - dy
        
        while True:
            # Başlangıç ve bitiş noktası hariç ara noktalara bak
            if (x, y) != start and (x, y) != end:
                # Harita sınırları kontrolü (teorik olarak gerekmez ama güvenli)
                if 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT:
                    # Engel varsa (Duvar=1 veya Gizli=2) görüşü engeller
                    if self.real_map[x][y] != 0:
                        return False
            
            if (x, y) == end:
                return True
                
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    """
    Obstacle Templates
    """
    OBSTACLE_TEMPLATES = [
        {
            "type": "puddle",
            "visual": "reflective liquid surface, looks shallow",
            "physics": "liquid, low friction",
            "score": 40
        },
        {
            "type": "mud_patch",
            "visual": "brown sticky surface, rough texture",
            "physics": "viscous, high resistance",
            "score": 60
        },
        {
            "type": "big_rock",
            "visual": "large grey solid object",
            "physics": "solid, immovable",
            "score": 90
        },
        {
            "type": "fire_pit",
            "visual": "burning wood, smoke",
            "physics": "hot, dangerous",
            "score": 95
        },
        {
            "type": "shallow_water",
            "visual": "clear water, seeing bottom",
            "physics": "liquid, drag",
            "score": 30
        },
        {
            "type": "dry_grass",
            "visual": "yellow dried grass",
            "physics": "soft, easy to traverse",
            "score": 10
        },
        {
            "type": "thick_swamp",
            "visual": "deep muddy water with vegetation",
            "physics": "very viscous, high sinking risk",
            "score": 75
        },
        {
            "type": "deep_sand",
            "visual": "loose fine sand, shifting surface",
            "physics": "unstable, wheels might dig in",
            "score": 70
        },
        {
            "type": "deep_pit",
            "visual": "dark hole with no visible bottom",
            "physics": "empty space, fall risk",
            "score": 100
        }
    ]

    def generate_obstacle_properties(self):
        """Sonradan eklenen engellere rastgele özellik atar."""
        base_prop = random.choice(self.OBSTACLE_TEMPLATES)
        
        # Create a unique copy
        props = base_prop.copy()
        
        # ID generation
        props["id"] = f"obj_{random.randint(1000, 9999)}"
        
        # Calculate Color based on Score: Green (0) -> Red (100)
        # Score is 0-100.
        # Red increases with score, Green decreases with score.
        score = props.get("score", 50)
        red_val = int(255 * (score / 100))
        green_val = int(255 * (1 - (score / 100)))
        
        # Clamp values
        red_val = max(0, min(255, red_val))
        green_val = max(0, min(255, green_val))
        
        props["color"] = (red_val, green_val, 0)
        
        return props

    def treat_as_wall(self, props):
        """Returns True if the obstacle is considered a wall (score > 80)."""
        return props.get("score", 0) > 80

    def send_to_llm(self, props):
        """Send to real Gemini for evaluation using threading."""
        print(f"[LLM] Requesting analysis for {props['id']} ({props['type']})...")
        
        def thread_target():
            result = self.analyzer.analyze_obstacle(props)
            with self.llm_lock:
                self.llm_results.append((props, result))

        thread = threading.Thread(target=thread_target)
        thread.daemon = True
        thread.start()

        self.llm_queue.append({
            "start_time": time.time(),
            "thread": thread,
            "props": props
        })

    def check_llm_status(self):
        """Checks the status of LLM threads and adjusts speed."""
        # 1. Process results from threads
        with self.llm_lock:
            while self.llm_results:
                res_props, result = self.llm_results.pop(0)
                
                if result and "score" in result:
                    res_score = result["score"]
                    print(f"[LLM] Gemini Verdict for {res_props['id']}: Score {res_score} ({result.get('rationale', '')})")
                    
                    obs_type = res_props.get("type")
                    if obs_type:
                        self.decision_cache[obs_type] = res_score
                        print(f"[CACHE] Saved {obs_type} -> {res_score}")
                    
                    # LOGGING TO FILE
                    try:
                        # Find the corresponding item in llm_queue to get start_time
                        # Note: The item might have been removed from llm_queue in step 2 if it finished fast,
                        # but we need to track it better. 
                        # Actually, llm_queue is cleaned up in step 2 (below), so it might still be there or we need a better way.
                        # Ideally, we should pass start_time with the result.
                        # For now, let's look it up or default to 0.
                        
                        start_time = time.time() # Default fallback
                        for q_item in self.llm_queue:
                             if q_item['props']['id'] == res_props['id']:
                                 start_time = q_item['start_time']
                                 break
                        
                        elapsed = time.time() - start_time
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Calculate Average Speed (Steps per Second)
                        total_game_time = time.time() - self.game_start_time
                        avg_speed = self.steps / total_game_time if total_game_time > 0 else 0
                        
                        log_entry = (
                            f"[{timestamp}] "
                            f"Model: {self.analyzer.model_id} | "
                            f"Duration: {elapsed:.2f}s | "
                            f"LLM Score: {res_score} | "
                            f"Steps: {self.steps} | "
                            f"Replans: {self.replans} | "
                            f"Discovered: {self.discovered_obstacles} | "
                            f"Path Len: {len(self.path) if self.path else 0} | "
                            f"Avg Speed: {avg_speed:.2f} steps/s | "
                            f"Chosen Speed: {self.speed_modifier:.1f}x\n"
                        )
                        
                        with open("log.txt", "a", encoding="utf-8") as f:
                            f.write(log_entry)
                    except Exception as e:
                        print(f"[LOG ERROR] Could not write to log.txt: {e}")

                    for pos, p in self.obstacle_props.items():
                        if p.get("type") == obs_type:
                            p["score"] = res_score
                            # Update Color Dynamically
                            red_val = int(255 * (res_score / 100))
                            green_val = int(255 * (1 - (res_score / 100)))
                            red_val = max(0, min(255, red_val))
                            green_val = max(0, min(255, green_val))
                            p["color"] = (red_val, green_val, 0)
                    
                    self.recalculate_path()
                else:
                    print(f"[LLM] Failed to get valid result for {res_props['id']}. Retrying later if visible.")

        # 2. Update speed based on oldest active thread
        if not self.llm_queue:
            self.speed_modifier = 1.0
            return

        current_time = time.time()
        active_items = []
        max_duration_so_far = 0

        for item in self.llm_queue:
            if item["thread"].is_alive():
                elapsed = current_time - item["start_time"]
                max_duration_so_far = max(max_duration_so_far, elapsed)
                active_items.append(item)
            # Threads that are finished but result not yet popped are handled by is_alive()=False
            
        self.llm_queue = active_items
        
        # Speed Control Logic
        if max_duration_so_far > 1.0:
            self.speed_modifier = 0.0 # STOP
        elif max_duration_so_far > 0.5:
            self.speed_modifier = 0.5 # SLOW
        else:
            self.speed_modifier = 1.0

    def log_encounter(self, car_pos, obstacle_pos, props):
        """Aracın pozisyonunu ve engelin pozisyonunu gösteren fonksiyon."""
        print(f"[ENCOUNTER] Car Pos: {car_pos} | Obstacle Pos: {obstacle_pos} | Properties: {props}")

    def log_mission_complete(self):
        """Destination reached logging."""
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            total_time = time.time() - self.game_start_time
            avg_speed = self.steps / total_time if total_time > 0 else 0
            
            log_entry = (
                f"[{timestamp}] MISSION COMPLETED | "
                f"Total Time: {total_time:.2f}s | "
                f"Total Steps: {self.steps} | "
                f"Avg Speed: {avg_speed:.2f} steps/s | "
                f"Replans: {self.replans} | "
                f"Obstacles Found: {self.discovered_obstacles}\n"
                f"{'-'*80}\n"
            )
            
            with open("log.txt", "a", encoding="utf-8") as f:
                f.write(log_entry)
            print("[LOG] Mission completion logged.")
            
        except Exception as e:
            print(f"[LOG ERROR] Could not write mission log: {e}")

    def check_sensors(self):
        """Manhattan (elmas) sensör alanı ile engel keşfi."""
        sensor_range = 4  # sunumda daha iyi görünsün diye 3 yerine 4 yaptım
        replan_needed = False

        cx, cy = self.car_pos

        for x in range(cx - sensor_range, cx + sensor_range + 1):
            for y in range(cy - sensor_range, cy + sensor_range + 1):
                if 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT:
                    # Elmas alan: |dx| + |dy| <= r
                    if abs(x - cx) + abs(y - cy) > sensor_range:
                        continue

                    # GÖRÜŞ HATTI KONTROLÜ
                    if not self.has_line_of_sight(self.car_pos, (x, y)):
                        continue

                    # Gerçekte gizli engel var ama biz bilmiyorsak
                    if self.real_map[x][y] == 2 and self.known_map[x][y] == 0:
                        # Eğer bu engel zaten kayıtlı değilse özellik üret
                        if (x, y) not in self.obstacle_props:
                            props = self.generate_obstacle_properties()
                            self.obstacle_props[(x, y)] = props
                            self.log_encounter(self.car_pos, (x, y), props)
                        else:
                            props = self.obstacle_props[(x, y)]

                        # Karar Mekanizması
                        obs_type = props.get("type")
                        
                        # 1. Cache Kontrolü
                        if obs_type in self.decision_cache:
                            # Only count if we haven't processed this object ID yet
                            if props.get("id") not in self.processed_cache_ids:
                                self.cache_hit_count += 1
                                self.processed_cache_ids.add(props.get("id"))
                                
                            # Bilinen tip -> Hemen skoru uygula
                            cached_score = self.decision_cache[obs_type]
                            if props.get("score") != cached_score:
                                props["score"] = cached_score
                                # Color update happens in draw loop or we can do it here too, but mostly visual.
                                
                            # LOGGING DECISION
                            if cached_score > 80:
                                print(f"[DECISION] {obs_type} (Score {cached_score}) -> IMPASSABLE. Treating as WALL. Rerouting.")
                                self.known_map[x][y] = 1
                                self.discovered_obstacles += 1
                                if (x, y) in self.path:
                                    replan_needed = True
                            else:
                                cost_increase = 1 + (cached_score / 10)
                                print(f"[DECISION] {obs_type} (Score {cached_score}) -> TRAVERSABLE (Cost {cost_increase:.1f}). Checking if shorter path exists...")
                                # Düşük skorsa sadece reroute gerekebilir (maliyet değişti)
                                if (x, y) in self.path:
                                    replan_needed = True

                        # 2. Eğer Cache'de yoksa ve Skor yüksekse (Duvar)
                        elif self.treat_as_wall(props):
                             # Yüksek skor -> Kesin Engel
                            print(f"[DECISION] Unknown High-Score Object (Score {props.get('score')}) -> IMPASSABLE. Treating as WALL.")
                            self.known_map[x][y] = 1 
                            self.discovered_obstacles += 1
                            if (x, y) in self.path:
                                replan_needed = True
                        
                        # 3. Eğer Cache'de yoksa ve Skor düşükse -> LLM'e Sor
                        else:
                            is_evaluating = any(item['props']['id'] == props['id'] for item in self.llm_queue)
                            if not is_evaluating:
                                print(f"[DECISION] Unknown Object {props.get('type')} -> Sending to LLM for analysis...")
                                self.send_to_llm(props)
                        
        if replan_needed:
            print("[ACTION] Path blocked or costs changed. Recalculating best path...")
            self.recalculate_path()

    def move_car(self):
        # Hız kontrolü
        self.check_llm_status()
        
        if self.speed_modifier == 0.0:
            return # Stop
            
        # Eğer yarı hızdaysa, basitçe her 2 frame'de bir hareket etmesini sağlayabiliriz
        # Veya şans faktörü koyarız
        if self.speed_modifier == 0.5:
             if random.random() < 0.5:
                 return # Skip this move frame

        if self.path and len(self.path) > 1:
            next_step = self.path[1]
            nx, ny = next_step

            # Güvenlik kontrolü: gerçek dünyada engel varsa "çarptık"
            if self.real_map[nx][ny] != 0:
                # Buraya girdiysek, ya unseen wall ya da düşük skorlu bir engeldir.
                # Düşük skorlu ise, "geçilebilir" (traversable) olduğu için çarpmayız, üstünden geçeriz.
                # Ancak 'Duvar' (1) veya Score>80 ise çarparız.
                
                is_hard_obstacle = (self.real_map[nx][ny] == 1) # Sabit duvar
                if not is_hard_obstacle and (nx, ny) in self.obstacle_props:
                    if self.treat_as_wall(self.obstacle_props[(nx, ny)]):
                        is_hard_obstacle = True
                
                if is_hard_obstacle:
                    # Çarpma!
                    self.known_map[nx][ny] = 1
                    self.discovered_obstacles += 1
                    self.recalculate_path()
                else:
                    # Geçilebilir engel (low score) - İlerle
                    self.car_pos = next_step
                    self.path.pop(0)
                    self.steps += 1
            else:
                self.car_pos = next_step
                self.path.pop(0)
                self.steps += 1
            
            # Check if reached destination
            if self.car_pos == self.end_pos:
                print("HEDEF ULAŞILDI! (Goal Reached)")
                self.log_mission_complete()
                self.paused = True

    def draw_hud(self):
        path_len = len(self.path) if self.path else 0
        lines = [
            f"[SPACE] Pause: {self.paused}",
            f"Algorithm: Weighted A*",
            f"[R] Reset",
            f"Steps: {self.steps}",
            f"Replans: {self.replans}",
            f"Discovered: {self.discovered_obstacles}",
            f"Path Len: {path_len}",
            f"Speed Mod: {self.speed_modifier:.1f}x",
            f"LLM Queue: {len(self.llm_queue)}",
            f"Cache Hits: {self.cache_hit_count}",
        ]
        y = 6
        for line in lines:
            surf = self.font.render(line, True, COLOR_TEXT)
            self.screen.blit(surf, (6, y))
            y += 18

    def draw(self):
        self.screen.fill(COLOR_BG)

        # 1) Izgara + Bilinen engeller (known_map)
        for x in range(MAP_WIDTH):
            for y in range(MAP_HEIGHT):
                rect = (x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(self.screen, COLOR_GRID, rect, 1)

                    # Draw obstacles if they are known walls OR discovered dynamic obstacles
                if self.known_map[x][y] == 1 or (x, y) in self.obstacle_props:
                    # Rengi belirle: Özelliği varsa onu kullan, yoksa standart duvar rengi
                    draw_color = COLOR_WALL
                    is_cached = False
                    
                    if (x, y) in self.obstacle_props:
                        props = self.obstacle_props[(x, y)]
                        draw_color = props["color"]
                        # Eğer tip cache'de varsa görsel bir fark ekleyebiliriz (örn: çerçeve)
                        if props.get("type") in self.decision_cache:
                            is_cached = True
                    
                    pygame.draw.rect(self.screen, draw_color, rect)
                    
                    if is_cached:
                        # Cache'lenmişse beyaz bir iç çerçeve çiz
                        pygame.draw.rect(self.screen, (255, 255, 255), rect, 1)

        # 2) Yol
        if self.path:
            for p in self.path:
                rect = (p[0] * CELL_SIZE, p[1] * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(self.screen, COLOR_PATH, rect)

        # 3) Başlangıç / Bitiş
        pygame.draw.rect(
            self.screen,
            COLOR_START,
            (self.start_pos[0] * CELL_SIZE, self.start_pos[1] * CELL_SIZE, CELL_SIZE, CELL_SIZE),
        )
        pygame.draw.rect(
            self.screen,
            COLOR_END,
            (self.end_pos[0] * CELL_SIZE, self.end_pos[1] * CELL_SIZE, CELL_SIZE, CELL_SIZE),
        )

        # 4) Araba
        car_rect = (self.car_pos[0] * CELL_SIZE, self.car_pos[1] * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        pygame.draw.rect(self.screen, COLOR_CAR, car_rect)

        # 5) Sensör alanı (görsel çerçeve)
        sensor_range = 4
        sensor_rect = (
            (self.car_pos[0] - sensor_range) * CELL_SIZE,
            (self.car_pos[1] - sensor_range) * CELL_SIZE,
            (sensor_range * 2 + 1) * CELL_SIZE,
            (sensor_range * 2 + 1) * CELL_SIZE,
        )
        pygame.draw.rect(self.screen, COLOR_SENSOR, sensor_rect, 1)

        # 6) HUD
        self.draw_hud()

        pygame.display.flip()

    def handle_mouse_wall(self):
        if pygame.mouse.get_pressed()[0]:
            mx, my = pygame.mouse.get_pos()
            grid_x, grid_y = mx // CELL_SIZE, my // CELL_SIZE
            if 0 <= grid_x < MAP_WIDTH and 0 <= grid_y < MAP_HEIGHT:
                # Gerçek dünyaya sabit duvar ekliyoruz (1)
                self.real_map[grid_x][grid_y] = 1
                self.known_map[grid_x][grid_y] = 1

                if (grid_x, grid_y) in self.path:
                    self.recalculate_path()

    def run(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.initialize_game()
                    elif event.key == pygame.K_SPACE:
                        self.paused = not self.paused

            # Mouse ile duvar ekleme
            self.handle_mouse_wall()

            if not self.paused:
                self.check_sensors()
                self.move_car()

            self.draw()
            self.clock.tick(FPS)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = PathfindingVisualizer()
    game.run()
