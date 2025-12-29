
import sys

class MockVisualizer:
    def __init__(self):
        self.llm_queue = []
        self.path = []
        self.car_pos = (0, 0)
        self.upgraded_log = []

    def send_to_llm(self, props, pos, distant_mode):
        print(f"[MOCK] send_to_llm called for {props['id']} with distant_mode={distant_mode}")
        self.upgraded_log.append((props, pos, distant_mode))

    def check_priority_upgrades(self):
        """
        Scans the LLM queue for 'Distant' tasks (Cluster B) that have become 'Close' (< 2 blocks).
        If found, they are removed from the Distant flow and re-submitted to Cluster A (Priority).
        """
        upgraded_indices = []
        
        for i, item in enumerate(self.llm_queue):
            if not item["distant_mode"]:
                continue # Already priority
                
            # Check min distance to path
            ox, oy = item["pos"]
            
            # Default to distance to car if no path
            min_dist = float('inf')
            
            if self.path:
                for px, py in self.path:
                    d = abs(ox - px) + abs(oy - py)
                    if d < min_dist:
                        min_dist = d
            else:
                # Fallback to car distance
                cx, cy = self.car_pos
                min_dist = abs(ox - cx) + abs(oy - cy)
            
            if min_dist < 2:
                # UPGRADE NEEDED
                print(f"[PRIORITY UPGRADE] Object {item['props']['id']} at ({ox},{oy}) came into Close Range (Dist {min_dist})!")
                upgraded_indices.append(i)
        
        # Process upgrades (iterate backwards to avoid index shifting)
        for i in sorted(upgraded_indices, reverse=True):
            item = self.llm_queue.pop(i)
            # Re-submit to Cluster A
            self.send_to_llm(item["props"], item["pos"], distant_mode=False)

def test_logic():
    viz = MockVisualizer()
    
    # Scenario:
    # Car at (0,0)
    # Path is a straight line upwards: (0,0) -> (0,5)
    viz.car_pos = (0,0)
    viz.path = [(0,0), (0,1), (0,2), (0,3), (0,4), (0,5)]
    
    # Item 1: Obstacle at (10, 10). Should NOT upgrade.
    item1 = {
        "distant_mode": True,
        "props": {"id": "obj_far"},
        "pos": (10, 10)
    }
    
    # Item 2: Obstacle at (1, 3). Close to path ((0,3) dist 1). Should UPGRADE.
    # Note: Distance to car (0,0) is 1+3=4 (Old logic would fail)
    item2 = {
        "distant_mode": True,
        "props": {"id": "obj_near_path"},
        "pos": (1, 3)
    }
    
    viz.llm_queue = [item1, item2]
    
    print("Running check_priority_upgrades...")
    viz.check_priority_upgrades()
    
    # Assertions
    # Queue should only have item1 left
    if len(viz.llm_queue) == 1 and viz.llm_queue[0]["props"]["id"] == "obj_far":
        print("PASS: Far object remained in queue.")
    else:
        print(f"FAIL: Queue state incorrect. Len: {len(viz.llm_queue)}")
        
    # Upgraded log should have obj_near_path
    if len(viz.upgraded_log) == 1:
        props, pos, mode = viz.upgraded_log[0]
        if props["id"] == "obj_near_path" and mode == False:
            print("PASS: Near-path object upgraded to Priority (Cluster A).")
        else:
            print("FAIL: Upgrade log content incorrect.")
    else:
        print(f"FAIL: Upgrade log length incorrect: {len(viz.upgraded_log)}")

if __name__ == "__main__":
    test_logic()
