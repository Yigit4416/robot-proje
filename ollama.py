import requests
import json
import threading
import time

class OllamaAnalyzer:
    def __init__(self):
        # Multi-Model Fleet
        self.models = [
            "ministral-3:3b", # Correct tag based on `ollama list` output
            "qwen2.5:1.5b"
        ]
        
        # Load Balance State
        self.queue_depths = {m: 0 for m in self.models}
        self.avg_times = {m: 1.0 for m in self.models} # Default 1s
        self.counts = {m: 0 for m in self.models}     # For moving average
        
        self.active_ids = set() # Deduplication
        self.lock = threading.Lock()
        
        self.api_url = "http://localhost:11434/api/chat"
        
        # System prompt'u yükle
        try:
            with open("system_prompt.md", "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
        except FileNotFoundError:
            self.system_prompt = "Analyze logic for robot navigation. Output JSON with 'score', 'rationale', and 'label'."

    def is_at_capacity(self, limit):
        """Checks if all models have reached the queue limit."""
        with self.lock:
            # If ANY model is below limit, we are not at capacity
            # (Because select_best_model will pick that one)
            for m in self.models:
                if self.queue_depths[m] < limit:
                    return False
            return True

    def select_best_model(self):
        """
        Load Balancing Algorithm:
        1. Priority: Free models (Queue=0) -> Pick fastest avg_time.
        2. Fallback: Lowest Queue -> Tie-break fastest avg_time.
        """
        with self.lock:
            # 1. Look for free models
            free_models = [m for m in self.models if self.queue_depths[m] == 0]
            if free_models:
                # Pick the one with lowest average response time
                return min(free_models, key=lambda m: self.avg_times[m])
            
            # 2. All busy, pick lowest queue
            return min(self.models, key=lambda m: (self.queue_depths[m], self.avg_times[m]))

    def analyze_obstacle(self, obstacle_props, context_examples=None, forced_model=None):
        """Send obstacle to Ollama via Load Balancer."""
        
        obs_id = obstacle_props.get("id")
        
        with self.lock:
            # Note: For warmup, we might reuse 'warmup' id, so we skip dedup check if forcing
            if not forced_model: 
                if obs_id in self.active_ids:
                    return None # Already processing
                self.active_ids.add(obs_id)
        
        # Select Model
        if forced_model:
            model_id = forced_model
        else:
            model_id = self.select_best_model()
        
        with self.lock:
            self.queue_depths[model_id] += 1
            
        start_t = time.time()
        
        try:
            clean_props = {k: v for k, v in obstacle_props.items() if k not in ["id", "color", "score"]}
            
            user_content = f"Analyze this obstacle: {json.dumps(clean_props)}"
            
            # Few-Shot Context Logic
            final_messages = [{"role": "system", "content": self.system_prompt}]
            
            if context_examples:
                example_text = "Here are some known obstacles and their scores for reference:\n"
                for i, (k, v) in enumerate(context_examples.items()):
                     example_text += f"{i+1}. {k}: Score {v} (Type: {k})\n"
                final_messages.append({"role": "user", "content": example_text})
                
            final_messages.append({"role": "user", "content": user_content})

            payload = {
                "model": model_id,
                "messages": final_messages,
                "stream": False,
                "format": "json"
            }
            
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            content = data["message"]["content"]
            
            # Parsing
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Fallback extraction
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                else:
                    result = {"score": 50, "rationale": "Raw Parse Failed", "label": "Unknown"}

            duration = time.time() - start_t
            
            # Update Stats
            with self.lock:
                self.queue_depths[model_id] -= 1
                # Simple Moving Average
                n = self.counts[model_id]
                self.avg_times[model_id] = (self.avg_times[model_id] * n + duration) / (n + 1)
                self.counts[model_id] += 1
                self.active_ids.discard(obs_id)

            # Metadata for the caller
            result["_meta_model"] = model_id
            result["_meta_duration"] = duration
            
            return result
            
        except requests.exceptions.RequestException as e:
            print(f"[LLM Error] Connection error with {model_id}: {e}")
            with self.lock:
                self.queue_depths[model_id] -= 1
                self.active_ids.discard(obs_id)
            return None
        except json.JSONDecodeError as e:
            print(f"[LLM Error] JSON Decode Error with {model_id}: {e}")
            with self.lock:
                self.queue_depths[model_id] -= 1
                self.active_ids.discard(obs_id)
            return None
        except Exception as e:
            print(f"[LLM Error] Unexpected error with {model_id}: {e}")
            with self.lock:
                self.queue_depths[model_id] -= 1
                self.active_ids.discard(obs_id)
            return None

# Test için (sadece bu dosya çalıştırılırsa)
if __name__ == "__main__":
    analyzer = OllamaAnalyzer()
    test_obstacle = {
        "type": "puddle",
        "visual": "reflective liquid surface, looks shallow",
        "physics": "liquid, low friction"
    }
    result = analyzer.analyze_obstacle(test_obstacle)
    print("Yanıt:")
    print(json.dumps(result, indent=2))
