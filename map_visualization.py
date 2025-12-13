import pygame
import sys
import heapq
import time
import random

# Constants
MAP_WIDTH = 300
MAP_HEIGHT = 600
CELL_SIZE = 5 # Increased size as requested
# Window dimensions calculated from map size
WINDOW_WIDTH = MAP_WIDTH * CELL_SIZE
WINDOW_HEIGHT = MAP_HEIGHT * CELL_SIZE

# Colors (R, G, B)
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_RED = (255, 0, 0)
COLOR_GRAY = (50, 50, 50)
COLOR_BLUE = (0, 0, 255) # Color for the car
COLOR_GREEN = (0, 255, 0) # Color for the path
COLOR_PINK = (255, 105, 180) # Color for dynamic obstacles



def create_map(width, height):
    """
    Creates a 2D list representing the map.
    Returns a list of lists where map[x][y] represents the block at (x, y).
    """
    # Create a 2D list filled with 0s (representing empty space)
    # Using list comprehension for cleaner initialization
    game_map = [[0 for _ in range(height)] for _ in range(width)]
    return game_map

def insert_to_block(game_map, x, y, value):
    """
    [USER REMINDER]
    Use this function to insert things into blocks later on!
    
    Parameters:
    - game_map: The 300x600 list
    - x: The x coordinate (0 to 299)
    - y: The y coordinate (0 to 599)
    - value: The thing you want to add to the block (e.g., an object, ID, or property)
    """
    if 0 <= x < len(game_map) and 0 <= y < len(game_map[0]):
        game_map[x][y] = value
        print(f"Block at ({x}, {y}) updated to {value}")
    else:
        print(f"Error: Coordinates ({x}, {y}) are out of bounds.")

def heuristic(a, b):
    """Manhattan distance heuristic for A*"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def find_path_astar(game_map, start, end):
    """
    Finds the shortest path from start to end using A* Algorithm.
    """
    rows = len(game_map)
    cols = len(game_map[0])
    
    # Priority queue stores: (f_score, x, y)
    # f_score = g_score + h_score
    queue = [(0, start)]
    
    g_score = {start: 0}
    f_score = {start: heuristic(start, end)}
    
    came_from = {start: None}
    
    directions = [(0, 1), (0, -1), (1, 0), (-1, 0)] 
    
    # Check for timeout or max iterations to prevent freezing
    iterations = 0
    max_iterations = 200000 
    
    while queue:
        iterations += 1
        if iterations > max_iterations:
             print("A* took too long, giving up.")
             break

        current_f, current_node = heapq.heappop(queue)
        
        if current_node == end:
            # Reconstruct path
            path = []
            curr = end
            while curr:
                path.append(curr)
                curr = came_from[curr]
            path.reverse()
            return path
        
        # If we found a path with worse f_score already, skip
        # (Though with consistent heuristic, first pop is optimal)
        
        cx, cy = current_node
        
        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            
            if 0 <= nx < rows and 0 <= ny < cols:
                if game_map[nx][ny] != 0:
                    continue
                
                tentative_g_score = g_score[current_node] + 1
                
                if tentative_g_score < g_score.get((nx, ny), float('inf')):
                    came_from[(nx, ny)] = current_node
                    g_score[(nx, ny)] = tentative_g_score
                    f = tentative_g_score + heuristic((nx, ny), end)
                    f_score[(nx, ny)] = f
                    heapq.heappush(queue, (f, (nx, ny)))

    print("No path found.")
    return []

def initialize_display():
    """
    Initializes Pygame and creates the display window.
    """
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("300x600 Map Visualization (A*)")
    return screen

def draw_grid(screen):
    """Draws the grid lines."""
    # Vertical lines
    for x in range(MAP_WIDTH + 1):
        pygame.draw.line(screen, COLOR_GRAY, (x * CELL_SIZE, 0), (x * CELL_SIZE, WINDOW_HEIGHT))
    # Horizontal lines
    for y in range(MAP_HEIGHT + 1):
        pygame.draw.line(screen, COLOR_GRAY, (0, y * CELL_SIZE), (WINDOW_WIDTH, y * CELL_SIZE))

def draw_map(screen, game_map):
    """
    Draws the map obstacles and grid.
    """
    screen.fill(COLOR_BLACK) # Clear screen

    # 1. Draw active cells
    for x in range(MAP_WIDTH):
        for y in range(MAP_HEIGHT):
            cell_value = game_map[x][y]
            if cell_value == 1: # Static Wall
                rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(screen, COLOR_RED, rect)
            elif cell_value == 2: # Dynamic Obstacle
                rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(screen, COLOR_PINK, rect)
    
    # 2. Draw grid
    draw_grid(screen)

def draw_path(screen, path):
    """Draws the path in green."""
    for (x, y) in path:
        rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
        pygame.draw.rect(screen, COLOR_GREEN, rect)

def draw_car(screen, position):
    """Draws the car as a blue block."""
    x, y = position
    rect = pygame.Rect(x * CELL_SIZE, y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
    pygame.draw.rect(screen, COLOR_BLUE, rect)


def handle_events():
    """
    Handles Pygame events like closing the window.
    Returns False if the game should quit, True otherwise.
    """
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
    return True

def main():
    """
    Main execution function.
    """
    # 1. Create the map
    my_map = create_map(MAP_WIDTH, MAP_HEIGHT)
    
    # 2. Add Obstacles (Walls)
    print("Adding obstacles...")
    # Wall 1: Horizontal wall blocking the way down
    for x in range(0, 250):
        insert_to_block(my_map, x, 150, 1)
        
    # Wall 2: Vertical wall blocking the right side
    for y in range(300, 500):
        insert_to_block(my_map, 200, y, 1)
        
    # Wall 3: Another horizontal wall
    for x in range(50, 300):
        insert_to_block(my_map, x, 400, 1)

    # 3. Initialize Known Map (What the car knows initially - only walls)
    known_map = [row[:] for row in my_map]

    # 4. Add Dynamic Obstacles (Hidden from car initially)
    print("Adding random dynamic obstacles...")
    for _ in range(1000): # Back to 100 for safety, 1000 was too much for drawing loop too! (User changed it manually though)
        rx = random.randint(0, MAP_WIDTH - 1)
        ry = random.randint(0, MAP_HEIGHT - 1)
        # Avoid start and end areas
        if (rx < 20 and ry < 20) or (rx > MAP_WIDTH - 20 and ry > MAP_HEIGHT - 20):
            continue
        if my_map[rx][ry] == 0:
             for dx in range(3):
                 for dy in range(3):
                     if 0 <= rx+dx < MAP_WIDTH and 0 <= ry+dy < MAP_HEIGHT:
                        insert_to_block(my_map, rx+dx, ry+dy, 2) 

    # 5. Setup display
    screen = initialize_display()
    
    # 6. Pathfinding Setup
    start_pos = (0, 0)
    end_pos = (MAP_WIDTH - 1, MAP_HEIGHT - 1)
    
    my_map[start_pos[0]][start_pos[1]] = 0
    my_map[end_pos[0]][end_pos[1]] = 0
    known_map[start_pos[0]][start_pos[1]] = 0
    known_map[end_pos[0]][end_pos[1]] = 0
    
    # Initial path using A*
    print("Calculating initial path with A*...")
    path = find_path_astar(known_map, start_pos, end_pos)
    
    car_position = start_pos
    path_index = 0
    
    clock = pygame.time.Clock()
    last_move_time = time.time()
    
    running = True
    while running:
        running = handle_events()
        
        # --- Optimized Sensor Logic ---
        recalculate = False
        
        # Only check the NEXT 5 STEPS on the path
        if path:
            # We look ahead from current path_index
            lookahead_range = 5
            for i in range(1, lookahead_range + 1):
                idx = path_index + i
                if idx < len(path):
                    px, py = path[idx]
                    # Check if this specific future step is blocked in REALITY
                    # but unknown to us
                    if my_map[px][py] == 2 and known_map[px][py] == 0:
                        known_map[px][py] = 2 # Discover it
                        recalculate = True
                        print(f"Path blocked at {px},{py}! Recalculating...")
                        break # One block is enough to force replan
        
        if recalculate:
            # Replan from current position
            new_path = find_path_astar(known_map, car_position, end_pos)
            if new_path:
                path = new_path
                path_index = 0 
            else:
                print("No path found!")
                path = []

        # --- Car Movement ---
        current_time = time.time()
        if path and path_index < len(path):
            if current_time - last_move_time >= 0.01: 
                car_position = path[path_index]
                path_index += 1
                last_move_time = current_time
        
        draw_map(screen, my_map)
        if path:
            draw_path(screen, path) 
        draw_car(screen, car_position)
        
        pygame.display.flip()
        clock.tick(60) 
        
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()


# To run the game (at least in linux) use this command:
# SDL_VIDEODRIVER=wayland python3 map_visualization.py
# Consider using D lite algorith for path finding