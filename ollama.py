import requests
import json
import os

class OllamaAnalyzer:
    def __init__(self):
        # Using qwen2.5:1.5b as requested by the user
        self.model_id = "qwen2.5:1.5b"
        self.api_url = "http://localhost:11434/api/chat"
        
        # System prompt'u yükle
        try:
            with open("system_prompt.md", "r", encoding="utf-8") as f:
                self.system_instruction = f.read()
        except FileNotFoundError:
            self.system_instruction = "Analyze logic for robot navigation. Output JSON with 'score', 'rationale', and 'label'."

    def analyze_obstacle(self, obstacle_props):
        """Engeli analiz eder ve JSON yanıtı döner."""
        # props içinden id ve color gibi gereksizleri temizle
        clean_props = {k: v for k, v in obstacle_props.items() if k not in ["id", "color", "score"]}
        prompt = f"Analyze this obstacle: {json.dumps(clean_props)}"
        
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "format": "json" # Force JSON output
        }
        
        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            # Ollama response structure: {"model":..., "created_at":..., "message": {"role": "assistant", "content": "..."}}
            content = result.get("message", {}).get("content", "")
            
            if content:
                print(f"[Ollama] Raw response: {content}") # Debugging
                return json.loads(content)
            return None
        except requests.exceptions.RequestException as e:
            print(f"[LLM Error] Connection error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"[LLM Error] JSON Decode Error: {e}")
            return None
        except Exception as e:
            print(f"[LLM Error] Unexpected error: {e}")
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
