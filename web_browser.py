import requests
from bs4 import BeautifulSoup
import re

def browse_url(url: str) -> str:
    """
    Browses the given URL, extracts the primary text content from the webpage, 
    and returns a clean, summarized text version. 
    Use this tool whenever the user provides a specific URL/link and asks you to 
    read, check, fetch, look at, or analyze the content of that page.
    
    Args:
        url: The web page URL to browse/fetch.
    
    Returns:
        The extracted main text content of the webpage or an error message.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return f"Error browsing URL: {e}"
        
    try:
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script, style, head, title, metadata and navigation/footer elements
        for element in soup(["script", "style", "head", "title", "meta", "noscript", "header", "footer", "nav"]):
            element.decompose()
            
        # Get text
        text = soup.get_text(separator="\n")
        
        # Clean whitespace and empty lines
        lines = [line.strip() for line in text.splitlines()]
        chunks = [phrase.strip() for line in lines for phrase in line.split("  ")]
        clean_text = "\n".join(chunk for chunk in chunks if chunk)
        
        # Limit to 8000 characters
        if len(clean_text) > 8000:
            clean_text = clean_text[:8000] + "\n\n[Content truncated due to length limits...]"
            
        return clean_text
    except Exception as e:
        return f"Error parsing webpage content: {e}"
