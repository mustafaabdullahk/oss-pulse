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
import langdetect

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

    def _random_user_agent(self) -> str:
        """Generate random user agent"""
        agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        ]
        return random.choice(agents)

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
        """Generate tweet content using Ollama deepseek-coder with language check"""
        name = repo.get('name', 'Unnamed Project')
        description = repo.get('description', 'No description available.')
        
        # Only check description for non-English content
        try:
            if description and description.strip() and langdetect.detect(description) != 'en':
                print(f"Skipping non-English repository description: {name}")
                return ""
                
        except langdetect.LangDetectException:
            print(f"Language detection failed for: {name}")
            pass

        stars = repo.get('stargazers_count', 0)
        language = repo.get('language', 'Unknown')

        prompt = f"""Create an engaging technical tweet about this open-source project:
- Project: {name}
- Language: {language}
- Stars: {stars}
- Description: {description}

Guidelines:
- Keep under 250 characters
- DO NOT include URLs or links
- Highlight technical merits
- Include relevant hashtags (max 3)
- Emphasize why developers should check it out
- Use emojis sparingly
- Response MUST be in English
- DO NOT include any thinking process or explanations
- ONLY output the final tweet text"""

        try:
            response = ollama.generate(
                model=self.config.ollama_model,
                prompt=prompt,
                options={'max_tokens': 280, 'temperature': 0.7}
            )
            content = response['response'].strip()
            
            # Remove any <think> blocks
            if "<think>" in content:
                content = content.split("</think>")[-1].strip()
            
            # Clean up the content
            content = self._sanitize_tweet(content)
            content = content.replace(repo.get('html_url', ''), '').strip()
            
            # Remove quotes if present
            content = content.strip('"').strip()
            
            return content
        except Exception as e:
            print(f"LLM generation failed: {e}")
            return self._generate_fallback_content(repo)
        
    def take_screenshot(self, url: str) -> Optional[str]:
        """Capture centered README section screenshot"""
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

                    # Calculate centered capture area
                    square_size = 900
                    page_width = page.evaluate("document.documentElement.scrollWidth")
                    page_height = page.evaluate("document.documentElement.scrollHeight")

                    # Horizontal centering
                    readme_center_x = bbox["x"] + bbox["width"]/2
                    capture_x = max(0, min(
                        readme_center_x - square_size/2,
                        page_width - square_size
                    ))

                    # Vertical centering (focus on first 1200px)
                    capture_y = max(0, min(
                        bbox["y"] + 200,  # Start 200px below top of README
                        page_height - square_size
                    ))

                    safe_area = {
                        "x": capture_x,
                        "y": capture_y,
                        "width": square_size,
                        "height": square_size
                    }

                    # Add visual feedback for debugging
                    page.evaluate(f"""() => {{
                        const div = document.createElement('div');
                        div.style.position = 'absolute';
                        div.style.left = '{safe_area['x']}px';
                        div.style.top = '{safe_area['y']}px';
                        div.style.width = '{safe_area['width']}px';
                        div.style.height = '{safe_area['height']}px';
                        div.style.border = '3px solid #ff0000';
                        div.style.zIndex = '9999';
                        document.body.appendChild(div);
                    }}""")
                    page.wait_for_timeout(500)  # Let red box appear

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
        """Post tweet with enhanced rate limit handling"""
        max_retries = 3
        base_delay = 60
        
        for attempt in range(max_retries):
            try:
                # Check if already posted
                repo_url = repo['html_url']
                if repo_url in self.posted_urls:
                    print(f"Already posted about {repo_url}, skipping...")
                    return False

                # 1. Medya yükleme
                if screenshot_path and os.path.exists(screenshot_path):
                    self._check_media_limits()
                    media = self.media_client.media_upload(
                        screenshot_path, 
                        media_category="tweet_image"
                    )
                    self.rate_limit_tracker.update_from_headers(
                        self.media_client.last_response.headers, 
                        'media_upload'
                    )

                # 2. Create main tweet
                self._check_tweet_limits()
                tweet = self.twitter_client.create_tweet(
                    text=content,
                    media_ids=[media.media_id] if media else None
                )

                # 3. Add repository link as reply
                if tweet.data['id']:
                    reply_text = f"🔗 {repo_url}"
                    self.twitter_client.create_tweet(
                        text=reply_text,
                        in_reply_to_tweet_id=tweet.data['id']
                    )

                # Update posted URLs set
                self.posted_urls.add(repo_url)
                self._log_success(repo, content, screenshot_path, tweet.data['id'])

                # Add random human-like variations
                # Randomize tweet length
                if len(content) > 200 and random.random() < 0.3:
                    content = content[:197] + "..."

                # Randomize hashtag order
                hashtags = [word for word in content.split() if word.startswith("#")]
                if len(hashtags) > 1 and random.random() < 0.5:
                    random.shuffle(hashtags)
                    content = ' '.join([word for word in content.split() if not word.startswith("#")] + hashtags)

                # Random delay between actions
                time.sleep(random.uniform(2.5, 8.2))

                return True

            except tweepy.TooManyRequests as e:
                # Parse rate limit headers
                headers = e.response.headers
                limit = int(headers.get('x-rate-limit-limit', 50))
                remaining = int(headers.get('x-rate-limit-remaining', 0))
                reset_time = int(headers.get('x-rate-limit-reset', time.time() + 900))
                
                # Calculate wait time with jitter
                wait_time = max(reset_time - time.time(), 300) + random.randint(0, 120)
                
                print(f"Rate limit: {remaining}/{limit} remaining")
                print(f"Next window resets at: {time.ctime(reset_time)}")
                print(f"Waiting {wait_time//60} minutes {wait_time%60} seconds")
                
                time.sleep(wait_time)
                continue

            except tweepy.TweepyException as e:
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 15)
                    print(f"Retrying in {sleep_time:.1f} seconds...")
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
        """Main execution loop with randomized intervals"""
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

                # Generate content and check if it's valid
                tweet_content = self.generate_tweet_content(repo)
                if not tweet_content:  # Skip if content is empty
                    print(f"Skipping repository due to language: {repo['html_url']}")
                    continue

                screenshot_path = self.take_screenshot(repo['html_url'])

                if self.post_tweet(tweet_content, repo, screenshot_path):
                    print("Tweet posted successfully!")
                    # Random delay between 45-75 minutes
                    delay = random.randint(2700, 4500)  # 45-75 minutes
                    time.sleep(delay)
                else:
                    # Shorter delay for failures
                    delay = random.randint(600, 1800)  # 10-30 minutes
                    print(f"Posting failed, retrying in {delay//60} minutes...")
                    time.sleep(delay)

            except KeyboardInterrupt:
                print("\nShutting down gracefully...")
                break
            except Exception as e:
                print(f"Critical error: {e}")
                time.sleep(random.randint(300, 900))

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