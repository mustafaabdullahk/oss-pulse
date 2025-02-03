import os
import time
import random
import requests
import tweepy
import ollama
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import List, Dict, Optional
from dataclasses import dataclass
from playwright.sync_api import sync_playwright
from pathlib import Path

@dataclass
class Config:
    """Configuration settings for the bot."""
    posts_per_hour: int
    twitter_api_key: str
    twitter_api_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    twitter_bearer_token: str
    github_token: Optional[str] = None
    ollama_model: str = "deepseek-coder"
    screenshot_dir: str = "screenshots"

class RateLimitTracker:
    """Real-time rate limit tracking using Twitter API headers"""
    def __init__(self):
        self.limits = {
            'tweet_create': {'limit': 50, 'remaining': 50, 'reset': 0},
            'media_upload': {'limit': 50, 'remaining': 50, 'reset': 0}
        }

    def update_from_headers(self, headers: dict, endpoint: str):
        """Update limits from API response headers"""
        if not headers:
            return

        limit = int(headers.get('x-rate-limit-limit', self.limits[endpoint]['limit']))
        remaining = int(headers.get('x-rate-limit-remaining', self.limits[endpoint]['remaining']))
        reset = int(headers.get('x-rate-limit-reset', self.limits[endpoint]['reset']))

        self.limits[endpoint] = {
            'limit': limit,
            'remaining': remaining,
            'reset': reset
        }

    def get_wait_time(self, endpoint: str) -> int:
        """Calculate remaining time until reset"""
        reset_time = self.limits[endpoint]['reset']
        return max(reset_time - int(time.time()) + 2, 0)

class RepoTweetBot:
    def __init__(self, config: Config):
        self.config = config
        self.sleep_interval = 3600 / config.posts_per_hour
        self.log_file = "generated_tweets.log"
        self.posted_urls = self._load_posted_urls()
        self.rate_limit_tracker = RateLimitTracker()
        self._setup_directories()
        self.twitter_client = self._init_twitter()
        self.media_client = self._init_media_api()

    def _setup_directories(self):
        """Create required directories with error handling"""
        try:
            screenshot_dir = Path(self.config.screenshot_dir)
            screenshot_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Directory creation failed: {e}")

    def _init_twitter(self) -> tweepy.Client:
        """Initialize Twitter API v2 client with OAuth1.1"""
        return tweepy.Client(
            consumer_key=self.config.twitter_api_key,
            consumer_secret=self.config.twitter_api_secret,
            access_token=self.config.twitter_access_token,
            access_token_secret=self.config.twitter_access_token_secret,
            wait_on_rate_limit=True
        )

    def _init_media_api(self) -> tweepy.API:
        """Initialize v1.1 API for media uploads"""
        auth = tweepy.OAuth1UserHandler(
            consumer_key=self.config.twitter_api_key,
            consumer_secret=self.config.twitter_api_secret,
            access_token=self.config.twitter_access_token,
            access_token_secret=self.config.twitter_access_token_secret
        )
        return tweepy.API(auth)
    
    def fetch_github_projects(self) -> List[Dict]:
        """Scrape trending repositories from GitHub's trending page"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                try:
                    # Navigate to trending page
                    page.goto("https://github.com/trending", timeout=60000)
                    page.wait_for_selector(".Box-row", timeout=30000)
                    
                    # Extract repository information
                    repos = []
                    items = page.query_selector_all(".Box-row")
                    
                    for item in items:
                        try:
                            # Extract basic info
                            title_element = item.query_selector("h2 a")
                            url = "https://github.com" + title_element.get_attribute("href")
                            name = title_element.inner_text().strip().replace(" / ", "/")
                            
                            # Extract description
                            desc_element = item.query_selector("p")
                            description = desc_element.inner_text().strip() if desc_element else ""
                            
                            # Extract language
                            lang_element = item.query_selector("[itemprop='programmingLanguage']")
                            language = lang_element.inner_text().strip() if lang_element else "Unknown"
                            
                            # Extract stars
                            stars_element = item.query_selector("a[href$='/stargazers']")
                            stars = int(stars_element.inner_text().replace(",", "").strip()) if stars_element else 0
                            
                            repos.append({
                                "name": name,
                                "html_url": url,
                                "description": description,
                                "stargazers_count": stars,
                                "language": language
                            })
                            
                        except Exception as e:
                            print(f"Error parsing repo: {e}")
                            continue
                            
                    return repos
                    
                finally:
                    browser.close()
                    
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:  # GitHub rate limit
                reset_time = int(e.response.headers.get('X-RateLimit-Reset', 3600))
                print(f"GitHub rate limit exceeded. Resets at {time.ctime(reset_time)}")
                time.sleep(reset_time - time.time() + 60)  # Add buffer
                return []
            raise

    def generate_tweet_content(self, repo: Dict) -> str:
        """Generate tweet content using Ollama deepseek-coder"""
        name = repo.get('name', 'Unnamed Project')
        description = repo.get('description', 'No description available.')
        stars = repo.get('stargazers_count', 0)
        language = repo.get('language', 'Unknown')
        repo_url = repo.get('html_url', '')

        prompt = f"""Create an engaging technical tweet about this open-source project:
- Project: {name}
- Language: {language}
- Stars: {stars}
- Description: {description}
- URL: {repo_url}

Guidelines:
- Keep under 250 characters
- Highlight technical merits
- Include relevant hashtags (max 3)
- Emphasize why developers should check it out
- Use emojis sparingly"""

        try:
            response = ollama.generate(
                model=self.config.ollama_model,
                prompt=prompt,
                options={'max_tokens': 280, 'temperature': 0.7}
            )
            content = response['response'].strip()
            return self._sanitize_tweet(content)
        except Exception as e:
            print(f"LLM generation failed: {e}")
            return self._generate_fallback_content(repo)
        
    def take_screenshot(self, url: str) -> Optional[str]:
        """Capture square README section screenshot with validation"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 2000})
                
                try:
                    page.goto(url, timeout=60000)
                    
                    # Wait for README content with retries
                    readme_element = None
                    for _ in range(3):
                        try:
                            page.wait_for_selector("#readme, .markdown-body", state="visible", timeout=10000)
                            readme_element = page.locator("#readme, .markdown-body")
                            if readme_element.count() > 0:
                                break
                        except Exception as e:
                            print(f"Retrying README detection: {e}")
                            page.reload()
                    else:
                        raise Exception("Failed to find README section after 3 attempts")

                    # Scroll and measure
                    readme_element.scroll_into_view_if_needed()
                    page.wait_for_timeout(2000)  # Allow full render
                    
                    # Get validated bounding box
                    bbox = readme_element.bounding_box()
                    if not bbox or bbox['width'] == 0 or bbox['height'] == 0:
                        return None

                    # Ensure capture area stays within page bounds
                    square_size = 900
                    page_width = page.evaluate("document.documentElement.scrollWidth")
                    page_height = page.evaluate("document.documentElement.scrollHeight")
                    
                    safe_area = {
                        "x": max(0, min(bbox["x"], page_width - square_size)),
                        "y": max(0, min(bbox["y"], page_height - square_size)),
                        "width": min(square_size, page_width),
                        "height": min(square_size, page_height)
                    }

                    # Take screenshot
                    filename = f"{url.split('/')[-1]}_{int(time.time())}.png"
                    screenshot_path = Path(self.config.screenshot_dir) / filename
                    
                    page.screenshot(
                        path=str(screenshot_path),
                        clip=safe_area,
                        type="png",
                        animations="disabled",
                        timeout=30000
                    )
                    return str(screenshot_path)
                    
                except Exception as e:
                    print(f"Screenshot error: {e}")
                    return None
                finally:
                    browser.close()
                    
        except Exception as e:
            print(f"Screenshot failed for {url}: {e}")
            return None


    def _sanitize_tweet(self, text: str) -> str:
        """Clean up generated tweet text"""
        return text.split("```")[0].replace("**", "").strip()

    def _generate_fallback_content(self, repo: Dict) -> str:
        """Fallback content generation"""
        name = repo.get('name', 'Cool Project')
        desc = repo.get('description', 'A valuable open-source project')
        stars = repo.get('stargazers_count', 0)
        lang = repo.get('language', '')
        return f"🚀 Check out {name} - {desc[:100]}\n\n⭐ {stars} stars | {lang}\n#OpenSource #GitHub"

    def _load_posted_urls(self) -> set:
        """Load previously posted URLs from log file"""
        posted_urls = set()
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if "Posted: " in line:
                            url = line.split("Posted: ")[1].strip()
                            posted_urls.add(url)
        except Exception as e:
            print(f"Error loading posted URLs: {e}")
        return posted_urls

    def post_tweet(self, content: str, repo: Dict, screenshot_path: Optional[str] = None) -> bool:
        """Güncellenmiş tweet gönderme mekanizması"""
        max_retries = 5
        base_delay = 15
        media_ids = []
        main_tweet_id = None

        for attempt in range(max_retries):
            try:
                # 1. Medya yükleme
                if screenshot_path and os.path.exists(screenshot_path):
                    self._check_media_limits()
                    media = self.media_client.media_upload(
                        screenshot_path, 
                        media_category="tweet_image"
                    )
                    media_ids.append(media.media_id)
                    self.rate_limit_tracker.update_from_headers(
                        self.media_client.last_response.headers, 
                        'media_upload'
                    )

                # 2. Create main tweet
                self._check_tweet_limits()
                tweet = self.twitter_client.create_tweet(
                    text=content,
                    media_ids=media_ids or None
                )
                main_tweet_id = tweet.data['id']

                # 3. Add repository link as reply
                if main_tweet_id:
                    reply_text = f"🔗 {repo['html_url']}"
                    self.twitter_client.create_tweet(
                        text=reply_text,
                        in_reply_to_tweet_id=main_tweet_id
                    )

                self._log_success(repo, content, screenshot_path, main_tweet_id)
                return True

            except tweepy.TooManyRequests as e:
                endpoint = 'media_upload' if 'media/upload' in str(e) else 'tweet_create'
                wait_time = self.rate_limit_tracker.get_wait_time(endpoint)
                
                print(f"Rate limit exceeded for {endpoint}. Waiting {wait_time} seconds")
                time.sleep(wait_time + random.uniform(0, 5))
                continue

            except tweepy.TweepyException as e:
                print(f"Twitter API error: {str(e)}")
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 3)
                    print(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    return False

        return False

    def _check_media_limits(self):
        """Medya yükleme limitlerini kontrol et"""
        media_limits = self.rate_limit_tracker.limits['media_upload']
        if media_limits['remaining'] < 1:
            wait_time = self.rate_limit_tracker.get_wait_time('media_upload')
            print(f"Media upload limit reached. Waiting {wait_time} seconds")
            time.sleep(wait_time)

    def _check_tweet_limits(self):
        """Tweet gönderme limitlerini kontrol et"""
        tweet_limits = self.rate_limit_tracker.limits['tweet_create']
        if tweet_limits['remaining'] < 1:
            wait_time = self.rate_limit_tracker.get_wait_time('tweet_create')
            print(f"Tweet creation limit reached. Waiting {wait_time} seconds")
            time.sleep(wait_time)

    def _log_success(self, repo: Dict, content: str, screenshot_path: Optional[str], tweet_id: str):
        """Güncellenmiş log mekanizması"""
        log_entry = (
            f"\n[{datetime.now().ctime()}] Main Tweet ID: {tweet_id}\n"
            f"Posted: {repo['html_url']}\n"
            f"Content: {content}\n"
            f"Media: {screenshot_path or 'None'}\n"
            f"Rate Limits: {self.rate_limit_tracker.limits}\n"
            f"{'-'*50}"
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)

    def run(self):
        """Main execution loop with enhanced error handling"""
        print("Starting RepoTweetBot...")
        while True:
            try:
                projects = self.fetch_github_projects()
                if not projects:
                    print("No projects found, retrying in 1 hour...")
                    time.sleep(3600)
                    continue

                new_projects = [p for p in projects if p['html_url'] not in self.posted_urls]
                if not new_projects:
                    print("No new projects, refreshing in 2 hours...")
                    time.sleep(7200)
                    continue

                repo = random.choice(new_projects)
                print(f"Selected repository: {repo['html_url']}")

                # Generate content and screenshot
                tweet_content = self.generate_tweet_content(repo)
                screenshot_path = self.take_screenshot(repo['html_url'])

                if self.post_tweet(tweet_content, repo, screenshot_path):
                    print("Tweet posted successfully!")
                    time.sleep(self.sleep_interval)
                else:
                    print("Posting failed, retrying in 30 minutes...")
                    time.sleep(1800)

            except KeyboardInterrupt:
                print("\nShutting down gracefully...")
                break
            except Exception as e:
                print(f"Critical error: {e}")
                time.sleep(600)

def main():
    load_dotenv()
    
    config = Config(
        posts_per_hour=int(os.getenv("POSTS_PER_HOUR", 4)),
        twitter_api_key=os.getenv("TWITTER_API_KEY"),
        twitter_api_secret=os.getenv("TWITTER_API_SECRET"),
        twitter_access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
        twitter_access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
        twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
        github_token=os.getenv("GITHUB_TOKEN"),
        ollama_model=os.getenv("OLLAMA_MODEL", "deepseek-coder")
    )

    bot = RepoTweetBot(config)
    bot.run()

if __name__ == "__main__":
    main()