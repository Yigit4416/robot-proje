import pygame
import sys
import heapq
import random
import time
import threading
import datetime
from ollama import OllamaAnalyzer

# --- AYARLAR (CONSTANTS) ---
CELL_SIZE = 10
MAP_WIDTH = 80
MAP_HEIGHT = 60
WINDOW_WIDTH = MAP_WIDTH * CELL_SIZE
WINDOW_HEIGHT = MAP_HEIGHT * CELL_SIZE
FPS = 60  # Smoother UI, logic is now time-based
BLOCKS_PER_SECOND = 5.0 # Target speed

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
        pygame.display.set_caption("Bilinmeyen Ortamda Otonom Robot Navigasyonu")
        self.clock = pygame.time.Clock()
        
        # LLM Integration
        self.analyzer = OllamaAnalyzer()
        

        self.font = pygame.font.SysFont("consolas", 16)

        # Warmup (Now Non-Blocking / Threaded)
        self.warmup_llm()
        
        # Reset clock so the time spent in warmup doesn't count as the first frame's dt
        self.clock.tick(FPS) 

        self.running = True
        self.paused = False
        
        # LLM Integration
        
        self.llm_results = [] # Thread-safe results queue
        self.llm_lock = threading.Lock()
        
        # LLM Simulation State (Now used for tracking real threads)
        self.llm_queue = []  # List of {start_time, thread, props}
        self.speed_modifier = 0.0  # 0.0 initially (Wait for Warmup)
        self.is_warming_up = True
        self.warmup_thread = None
        self.move_accumulator = 0.0 # Time bucket for movement

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
        self.llm_call_count = 0

        self.initialize_game()

    def draw_loading_screen(self, current_task):
        self.screen.fill(COLOR_BG)
        
        # Title
        title = self.font.render("INITIALIZING AI SYSTEM...", True, COLOR_TEXT)
        self.screen.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, WINDOW_HEIGHT//2 - 40))
        
        # Task
        task = self.font.render(f"Warming up: {current_task}", True, (50, 200, 50))
        self.screen.blit(task, (WINDOW_WIDTH//2 - task.get_width()//2, WINDOW_HEIGHT//2 + 10))
        
        pygame.display.flip()

    def warmup_llm(self):
        """Starts the warmup process in a background thread."""
        def _warmup_task():
            print("------------------------------------------------")
            print("[SYSTEM] Warming up Multi-Model Cluster... (Background)")
            print("------------------------------------------------")
            dummy_prop = {"id": "warmup", "type": "warmup_pixel", "visual": "loading", "physics": "none"}
            
            for model in self.analyzer.models:
                print(f"   -> Warming up {model}...")
                try:
                    self.analyzer.analyze_obstacle(dummy_prop, forced_model=model)
                except:
                    pass
            
            print("[SYSTEM] Cluster Warmup Complete. Enabling Engines.")
            print("------------------------------------------------")
            self.is_warming_up = False # Signal completion
            self.speed_modifier = 1.0 # Auto-start

        self.warmup_thread = threading.Thread(target=_warmup_task)
        self.warmup_thread.daemon = True
        self.warmup_thread.start()

    def create_grid(self, default=0):
        return [[default for _ in range(MAP_HEIGHT)] for _ in range(MAP_WIDTH)]

    def initialize_game(self):
        self.real_map = self.create_grid(0)
        self.known_map = self.create_grid(0)
        self.move_accumulator = 0.0
        
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
        for _ in range(600): # Increased from 300 to 600
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
        # SAFE (< 50)
        {"type": "dry_grass", "visual": "yellow dried grass", "physics": "soft, easy to traverse"},
        {"type": "dirt_path", "visual": "packed dirt trail", "physics": "solid, high friction"},
        {"type": "asphalt", "visual": "grey cracked pavement", "physics": "hard, excellent grip"},
        {"type": "gravel", "visual": "small loose stones", "physics": "noisy but traversable"},
        {"type": "flowers", "visual": "patch of wildflowers", "physics": "soft, negligible resistance"},
        
        # CAUTION (50 - 80)
        {"type": "puddle", "visual": "reflective liquid surface, looks shallow", "physics": "liquid, low friction"},
        {"type": "mud_patch", "visual": "brown sticky surface, rough texture", "physics": "viscous, high resistance"},
        {"type": "shallow_water", "visual": "clear water, seeing bottom", "physics": "liquid, drag"},
        {"type": "sand_dune", "visual": "pile of soft sand", "physics": "shifting, risk of getting stuck"},
        {"type": "ice_patch", "visual": "glossy white surface", "physics": "extremely slippery, zero friction"},
        {"type": "rubble", "visual": "pile of broken bricks", "physics": "uneven, sharp edges"},

        # DANGER (> 80)
        {"type": "big_rock", "visual": "large grey solid object", "physics": "solid, immovable"},
        {"type": "fire_pit", "visual": "burning wood, smoke", "physics": "hot, dangerous"},
        {"type": "thick_swamp", "visual": "deep muddy water with vegetation", "physics": "very viscous, high sinking risk"},
        {"type": "deep_pit", "visual": "dark hole with no visible bottom", "physics": "empty space, fall risk"},
        {"type": "lava", "visual": "glowing molten rock", "physics": "deadly heat, instant destruction"},
        {"type": "concrete_wall", "visual": "solid reinforced concrete", "physics": "immovable wall"},
        {"type": "radioactive_waste", "visual": "glowing green goo", "physics": "toxic, corrosive"},
        {"type": "spike_trap", "visual": "sharp metal spikes", "physics": "puncture risk"},

        # MYSTERY (Unknowns - Not in KNOWN_SCORES)
        {"type": "mystery_box", "visual": "floating question mark box", "physics": "unknown"},
        {"type": "alien_monolith", "visual": "smooth black metal slab", "physics": "humming vibration"},
        {"type": "glitch_trap", "visual": "flickering pixels", "physics": "distorted reality"},
        {"type": "magnetic_field", "visual": "distorted air with blue sparks", "physics": "electronic interference"},
        {"type": "robot_scrap", "visual": "pile of rusted circuits and gears", "physics": "sharp metal debris"},
        {"type": "oil_slick", "visual": "shimmering oily pool", "physics": "extremely low friction"},
        {"type": "toxic_gas", "visual": "greenish-yellow haze", "physics": "corrosive atmosphere"},
    ]

    # Pre-defined Knowledge Base (Type -> Score)
    KNOWN_SCORES = {
        # Safe
        "dry_grass": 10, "dirt_path": 5, "asphalt": 0, "gravel": 15, "flowers": 5,
        # Caution
        "puddle": 40, "mud_patch": 60, "shallow_water": 50, "sand_dune": 65, "ice_patch": 70, "rubble": 55,
        # Danger
        "big_rock": 100, "fire_pit": 100, "thick_swamp": 90, "deep_pit": 100, 
        "lava": 100, "concrete_wall": 100, "radioactive_waste": 100, "spike_trap": 100 # Walls
    }

    def generate_obstacle_properties(self):
        """Sonradan eklenen engellere rastgele özellik atar."""
        
        # Split templates into Known and Unknown
        known_templates = [t for t in self.OBSTACLE_TEMPLATES if t["type"] in self.KNOWN_SCORES]
        unknown_templates = [t for t in self.OBSTACLE_TEMPLATES if t["type"] not in self.KNOWN_SCORES]
        
        # 50% Chance for Unknown (Mystery) Object
        if random.random() < 0.5 and unknown_templates:
            base_prop = random.choice(unknown_templates)
        else:
            base_prop = random.choice(known_templates)
        
        # Create a unique copy
        props = base_prop.copy()
        
        # ID generation
        props["id"] = f"obj_{random.randint(1000, 9999)}"
        
        # Initial color based on predefined score if available (Instant feedback)
        # If unknown, use a distinct "Mystery" color (Purple)
        score = self.KNOWN_SCORES.get(props["type"], None)
        
        if score is not None:
            # Calculate Color based on Score: Green (0) -> Red (100)
            red_val = int(255 * (score / 100))
            green_val = int(255 * (1 - (score / 100)))
            
            # Clamp values
            red_val = max(0, min(255, red_val))
            green_val = max(0, min(255, green_val))
            props["color"] = (red_val, green_val, 0)
            props["score"] = score # Assign score immediately if known
        else:
            # Unknown Object -> Purple/Magenta
            props["color"] = (200, 0, 200)
            # Do NOT assign score yet
        
        return props

    def treat_as_wall(self, props):
        """Returns True if the obstacle is considered a wall (score > 80)."""
        # First check if we have a resolved score in decision_cache
        if props["type"] in self.decision_cache:
            return self.decision_cache[props["type"]] > 80
            
        # Fallback for predefined scores (should generally happen via cache or direct lookup)
        return self.KNOWN_SCORES.get(props["type"], 0) > 80

    def send_to_llm(self, props, pos, distant_mode=False):
        """Send to real Gemini for evaluation using threading."""
        print(f"[LLM] Requesting analysis for {props['id']} ({props['type']})...")
        self.llm_call_count += 1
        
        # Context Injection: Add known examples to guide the model
        context_examples = {k: v for k, v in list(self.KNOWN_SCORES.items())[:5]} # Pick first 5 as examples
        
        def thread_target():
            # Pass our simplified known list as context
            if distant_mode:
                result = self.analyzer.analyze_distant_obstacle(props, context_examples)
            else:
                result = self.analyzer.analyze_obstacle(props, context_examples)
                
            with self.llm_lock:
                self.llm_results.append((props, result, distant_mode))

        thread = threading.Thread(target=thread_target)
        thread.daemon = True
        thread.start()

        self.llm_queue.append({
            "start_time": time.time(),
            "thread": thread,
            "props": props,
            "pos": pos,
            "distant_mode": distant_mode
        })

    def resolve_unknown_obstacle(self, x, y, score):
        """Called when LLM (or cache) decides a score for a previously unknown object."""
        # Update map based on verdict
        if score > 80:
             # It's a wall. Keep it as 1.
             self.known_map[x][y] = 1
             print(f"[RESOLVE] {x},{y} -> WALL (Score {score})")
        else:
             # It's safe/traversable. Remove wall marker.
             self.known_map[x][y] = 0
             print(f"[RESOLVE] {x},{y} -> SAFE/TRAVERSABLE (Score {score})")
             
             # Need to trigger pathfinding since a wall just opened up
             self.recalculate_path()

    def check_priority_upgrades(self):
        """
        Scans the LLM queue for 'Distant' tasks (Cluster B) that have become 'Close' (< 2 blocks).
        If found, they are removed from the Distant flow and re-submitted to Cluster A (Priority).
        """
        upgraded_indices = []
        
        for i, item in enumerate(self.llm_queue):
            if not item["distant_mode"]:
                continue # Already priority
                
            # Check current distance
            ox, oy = item["pos"]
            cx, cy = self.car_pos
            dist = abs(ox - cx) + abs(oy - cy)
            
            if dist < 2:
                # UPGRADE NEEDED
                print(f"[PRIORITY UPGRADE] Object {item['props']['id']} at ({ox},{oy}) came into Close Range (Dist {dist})!")
                upgraded_indices.append(i)
        
        # Process upgrades (iterate backwards to avoid index shifting)
        for i in sorted(upgraded_indices, reverse=True):
            item = self.llm_queue.pop(i)
            # Re-submit to Cluster A
            # Note: The old thread continues in background but its result will likely handle itself 
            # (or we could add a cancelled flag, but for now ignoring it is fine as 'send_to_llm' creates a new entry)
            # Actually, duplicate results might update the cache twice, which is harmless.
            self.send_to_llm(item["props"], item["pos"], distant_mode=False)


    def check_llm_status(self):
        """Checks the status of LLM threads and adjusts speed."""
        
        # 0. PRIORITY: WARMUP
        if self.is_warming_up:
            self.speed_modifier = 0.0
            return
            
        # Priority Upgrade Check
        self.check_priority_upgrades()

        # 1. Process results from threads
        with self.llm_lock:
            while self.llm_results:
                # UNPACK with distant_mode
                res_props, result, was_distant = self.llm_results.pop(0)
                
                if result and "score" in result:
                    res_score = result["score"]
                    used_model = result.get("_meta_model", "unknown")
                    cluster_name = "Cluster B" if was_distant else "Cluster A"
                    
                    # Requested Format: rule "cluster <one we are using> -- <model>"
                    print(f"{cluster_name} -- {used_model} | Verdict for {res_props['id']}: Score {res_score}")
                    
                    obs_type = res_props.get("type")
                    
                    if obs_type:
                        self.decision_cache[obs_type] = res_score
                        print(f"[CACHE] Saved {obs_type} -> {res_score}")
                    
                    # LOGGING TO FILE
                    try:
                        start_time = time.time() # Default fallback
                        for q_item in self.llm_queue:
                             if q_item['props']['id'] == res_props['id']:
                                 start_time = q_item['start_time']
                                 break
                        
                        elapsed = result.get("_meta_duration", time.time() - start_time)
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Calculate Average Speed (Steps per Second)
                        total_game_time = time.time() - self.game_start_time
                        avg_speed = self.steps / total_game_time if total_game_time > 0 else 0
                        
                        log_entry = (
                            f"[{timestamp}] "
                            f"Model: {used_model} | "
                            f"Duration: {elapsed:.2f}s | "
                            f"LLM Calls: {self.llm_call_count} | "
                            f"LLM Score: {res_score} | "
                            f"Steps: {self.steps} | "
                            f"Replans: {self.replans} | "
                            f"Discovered: {self.discovered_obstacles} | "
                            f"Path Len: {len(self.path) if self.path else 0} | "
                            f"Avg Speed: {avg_speed:.2f} steps/s | "
                            f"Target Speed: {BLOCKS_PER_SECOND} blk/s | "
                            f"Chosen Speed: {self.speed_modifier:.1f}x\n"
                        )
                        
                        with open("log.txt", "a", encoding="utf-8") as f:
                            f.write(log_entry)
                    except Exception as e:
                        print(f"[LOG ERROR] Could not write to log.txt: {e}")

                    # Update all existing instances of this type on the map
                    for pos, p in self.obstacle_props.items():
                        if p.get("type") == obs_type:
                            p["score"] = res_score
                            # Update Color
                            red_val = int(255 * (res_score / 100))
                            green_val = int(255 * (1 - (res_score / 100)))
                            red_val = max(0, min(255, red_val))
                            green_val = max(0, min(255, green_val))
                            p["color"] = (red_val, green_val, 0)
                            
                            # Resolve the wall status 
                            # (If it was waiting as a wall, this will clear it if safe)
                            px, py = pos
                            self.resolve_unknown_obstacle(px, py, res_score)
                    
                    self.recalculate_path()
                else:
                    print(f"[LLM] Failed to get valid result for {res_props['id']}. Retrying later if visible.")

        if self.llm_queue:
            # Active requests pending
            current_time = time.time()
            active_items = []
            
            # --- SPEED LOGIC ---
            # Default to Full Speed
            should_slow_down = False
            
            for item in self.llm_queue:
                if item["thread"].is_alive():
                    active_items.append(item)
                    # If ANY item uses 'Close' mode (distant_mode=False), we MUST slow down.
                    if not item["distant_mode"]:
                        should_slow_down = True
            
            self.llm_queue = active_items
            
            if self.llm_queue:
                if should_slow_down:
                     self.speed_modifier = 0.1 # SLOW CRAWL (0.1x) for Priority items
                else:
                     self.speed_modifier = 1.0 # FULL SPEED if only Distant items are in queue
            else:
                self.speed_modifier = 1.0
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
                f"Target Speed: {BLOCKS_PER_SECOND} blk/s | "
                f"Replans: {self.replans} | "
                f"LLM Calls: {self.llm_call_count} | "
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
                    if self.real_map[x][y] == 2 and (x, y) not in self.obstacle_props: 
                         # Note: logic changed slightly to allow re-checking if we don't have props yet
                         # but usually if we have props we've "discovered" it.
                        
                        # Eğer bu engel zaten kayıtlı değilse özellik üret
                        props = self.generate_obstacle_properties()
                        self.obstacle_props[(x, y)] = props
                        self.log_encounter(self.car_pos, (x, y), props)
                        
                        obs_type = props.get("type")
                        
                        # --- DECISION LOGIC ---
                        
                        # 1. Check Pre-defined Knowledge Base (INSTANT)
                        if obs_type in self.KNOWN_SCORES:
                            score = self.KNOWN_SCORES[obs_type]
                            props["score"] = score
                            self.decision_cache[obs_type] = score # Cache it
                            
                            # Update map directly
                            if score > 80: # WALL
                                self.known_map[x][y] = 1
                                print(f"[INSTANT] Known Danger: {obs_type} -> WALL")
                                replan_needed = True
                            else: # SAFE / CAUTION
                                # Traversable. map[x][y] stays 0 (or whatever it was).
                                # Cost will be calculated in A*
                                pass 
                                
                        # 2. Check Decision Cache (Previously LLM analyzed)
                        elif obs_type in self.decision_cache:
                            self.cache_hit_count += 1 # Increment hit counter
                            score = self.decision_cache[obs_type]
                            props["score"] = score
                            
                            if score > 80:
                                self.known_map[x][y] = 1
                                replan_needed = True
                                
                        # 3. UNKNOWN -> SAFETY FIRST
                        else:
                            # CRITICAL: Mark as WALL temporarily to prevent overlapping
                            self.known_map[x][y] = 1 
                            # print(f"[UNKNOWN] Mystery Object: {obs_type} -> Analyizing... (Marked as temp WALL)")
                            
                            # Send to LLM (Prevent duplicate requests for same TYPE and same ID)
                            # Check if we are already evaluating this TYPE or this specific ID
                            is_evaluating_id = any(item['props']['id'] == props['id'] for item in self.llm_queue)
                            is_evaluating_type = any(item['props']['type'] == obs_type for item in self.llm_queue)
                            
                            if not is_evaluating_id and not is_evaluating_type:
                                # QUEUE LIMIT CHECK: only send if fleet has capacity
                                if not self.analyzer.is_at_capacity(2):
                                    
                                    # --- DISTANCE LOGIC TO SPLIT CLUSTERS ---
                                    # Check distance from obstacle (x, y) to the closest point on the current path
                                    min_dist_to_path = float('inf')
                                    if self.path:
                                        for px, py in self.path:
                                            dist = abs(px - x) + abs(py - y)
                                            if dist < min_dist_to_path:
                                                min_dist_to_path = dist
                                    else:
                                        # If no path (e.g. at start), treat as "close" or "far" based on car
                                        min_dist_to_path = abs(self.car_pos[0] - x) + abs(self.car_pos[1] - y)

                                    # User Rule: At least 2 blocks away from our road (path) -> Distant Cluster
                                    if min_dist_to_path >= 2:
                                        print(f"[CLUSTER B] Routing {obs_type} (Dist: {min_dist_to_path}) to Distant Cluster (Qwen2.5)")
                                        self.send_to_llm(props, pos=(x,y), distant_mode=True)
                                    else:
                                        print(f"[CLUSTER A] Routing {obs_type} (Dist: {min_dist_to_path}) to Standard Cluster (Load Balanced)")
                                        self.send_to_llm(props, pos=(x,y), distant_mode=False)

                                    replan_needed = True # Because we just put a wall in front of us
                                else:
                                    print(f"[QUEUE FULL] Skipping LLM request for {obs_type} (Fleet Saturated)")
                        
                        self.discovered_obstacles += 1
                        
        if replan_needed:
            # print("[ACTION] Map updated. Recalculating path...")
            self.recalculate_path()

    def move_car(self, dt):
        # Hız kontrolü
        self.check_llm_status()
        
        if self.speed_modifier == 0.0:
            self.move_accumulator = 0.0
            return # Stop
            
        # Accumulate time
        self.move_accumulator += dt
        
        # Calculate delay per step based on blocks per second
        # If BLOCKS_PER_SECOND = 15, delay = 1/15 = 0.066s
        current_speed = BLOCKS_PER_SECOND * self.speed_modifier
        if current_speed <= 0:
            return
            
        step_delay = 1.0 / current_speed
        
        # Execute steps
        while self.move_accumulator >= step_delay:
            self.move_accumulator -= step_delay
            self.execute_step()

    def execute_step(self):
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
        
        status_text = f"Speed Mod: {self.speed_modifier:.1f}x"
        if self.is_warming_up:
            status_text += " (WARMING UP... WAIT)"
            
        lines = [
            f"[SPACE] Pause: {self.paused}",
            f"Algorithm: Weighted A*",
            f"[R] Reset",
            f"Steps: {self.steps}",
            f"Replans: {self.replans}",
            f"Discovered: {self.discovered_obstacles}",
            f"Path Len: {path_len}",
            status_text,
            f"LLM Queue: {len(self.llm_queue)}",
            f"Cache Hits: {self.cache_hit_count}",
        ]
        
        # Add Cluster Stats
        y = 6
        for line in lines:
            surf = self.font.render(line, True, COLOR_TEXT)
            self.screen.blit(surf, (6, y))
            y += 18
            
        # Draw Cluster Info at bottom left
        y_stats = WINDOW_HEIGHT - 60
        for m in self.analyzer.models:
             q = self.analyzer.queue_depths.get(m, 0)
             t = self.analyzer.avg_times.get(m, 0)
             stat_line = f"[{m}] Q:{q} | Avg:{t:.2f}s"
             surf = self.font.render(stat_line, True, (150, 150, 150))
             self.screen.blit(surf, (6, y_stats))
             y_stats += 15

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
                # ROBOT BUNU BİLMİYOR! (self.known_map güncellenmiyor)
                # Sensör görüşüne girince fark edecek.
                self.real_map[grid_x][grid_y] = 1

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
                # Pass delta time in seconds
                dt = self.clock.get_time() / 1000.0
                self.move_car(dt)

            self.draw()
            self.clock.tick(FPS)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = PathfindingVisualizer()
    game.run()
