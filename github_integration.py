import os
import requests
import logging

logger = logging.getLogger(__name__)


class GitHubIntegration:
    def __init__(self, repo_url: str, token: str = None):
        """
        repo_url: e.g. "https://github.com/dor2500/FixyBot" or "dor2500/FixyBot"
        """
        # Parse owner/repo from URL or direct string
        clean = repo_url.rstrip("/").replace("https://github.com/", "")
        parts = clean.split("/")
        self.owner = parts[0]
        self.repo = parts[1] if len(parts) > 1 else ""
        self.token = token
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

        self.repo_summary = ""

    def _api_get(self, endpoint: str):
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(f"GitHub API returned {resp.status_code} for {endpoint}")
        except Exception as e:
            logger.warning(f"GitHub API error: {e}")
        return None

    def fetch_repo_info(self) -> str:
        """Fetch repo metadata, file tree and README to build a summary for the system prompt."""
        lines = []

        # Repo metadata
        meta = self._api_get("")
        if meta:
            lines.append(f"שם: {meta.get('full_name', '')}")
            lines.append(f"תיאור: {meta.get('description', 'אין תיאור')}")
            lines.append(f"קישור: {meta.get('html_url', '')}")
            lines.append(f"שפה עיקרית: {meta.get('language', 'N/A')}")
            lines.append("")

        # File listing
        contents = self._api_get("contents/")
        if contents and isinstance(contents, list):
            lines.append("קבצים בפרויקט:")
            for item in contents:
                icon = "📁" if item["type"] == "dir" else "📄"
                lines.append(f"  {icon} {item['name']} — {item.get('html_url', '')}")
            lines.append("")

        # README
        readme = self._api_get("readme")
        if readme and readme.get("download_url"):
            try:
                r = requests.get(readme["download_url"], timeout=10)
                if r.status_code == 200:
                    # Trim to first 2000 chars to save tokens
                    readme_text = r.text[:2000]
                    lines.append(f"תוכן README (מקוצר):\n{readme_text}")
            except Exception:
                pass

        self.repo_summary = "\n".join(lines)
        logger.info(f"GitHub repo summary loaded ({len(self.repo_summary)} chars)")
        return self.repo_summary
