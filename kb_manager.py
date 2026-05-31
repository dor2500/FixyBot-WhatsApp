import os
import requests

class KBManager:
    def __init__(self, url: str, cache_path: str = "kb_cache.md"):
        self.url = url
        # Use an absolute or relative path inside the directory
        # If cache_path is just a filename, let's make it relative to the file's directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_path = os.path.join(current_dir, cache_path)
        self.kb_content = ""

    def load_kb(self) -> str:
        """Fetch the knowledge base from the URL and cache it.
        If the network request fails, fall back to the locally cached version.
        """
        try:
            print(f"Fetching knowledge base from {self.url}...")
            response = requests.get(self.url, timeout=10)
            if response.status_code == 200:
                self.kb_content = response.text
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    f.write(self.kb_content)
                print("Knowledge base successfully fetched and cached.")
                return self.kb_content
            else:
                print(f"Failed to fetch KB, status code: {response.status_code}")
        except Exception as e:
            print(f"Error fetching KB: {e}")
        
        # Fallback to cache if network request failed
        if os.path.exists(self.cache_path):
            print("Loading cached knowledge base...")
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.kb_content = f.read()
            return self.kb_content
        
        print("No cached knowledge base found.")
        return ""
