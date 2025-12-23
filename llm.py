import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Hata: .env dosyasında GOOGLE_API_KEY veya GEMINI_API_KEY bulunamadı!")
            
        self.client = genai.Client(api_key=api_key)
        # Using gemini-1.5-flash as it's stable, fast, and free.
        self.model_id = "gemini-2.5-flash-lite"
        
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
        
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config={
                    "system_instruction": self.system_instruction,
                    "response_mime_type": "application/json"
                }
            )
            # Yanıtı JSON olarak parse et
            if response.text:
                return json.loads(response.text)
            return None
        except Exception as e:
            print(f"[LLM Error] {e}")
            return None

# Test için (sadece bu dosya çalıştırılırsa)
if __name__ == "__main__":
    analyzer = GeminiAnalyzer()
    test_obstacle = {
        "type": "puddle",
        "visual": "reflective liquid surface, looks shallow",
        "physics": "liquid, low friction"
    }
    result = analyzer.analyze_obstacle(test_obstacle)
    print("Yanıt:")
    print(json.dumps(result, indent=2))