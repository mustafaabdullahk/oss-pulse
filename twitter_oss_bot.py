import os
import time
import random
import requests
import tweepy
import ollama
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

class RepoTweetBot:
    def __init__(self, config: Config):
        self.config = config
        self.sleep_interval = 3600 / config.posts_per_hour
        self.log_file = "generated_tweets.log"
        self.posted_urls = self._load_posted_urls()
        self._setup_directories()
        self.twitter_client_v2 = self._init_twitter_v2()
        self.twitter_client_v1 = self._init_twitter_v1()

    def _setup_directories(self):
        """Create required directories with error handling"""
        try:
            screenshot_dir = Path(self.config.screenshot_dir)
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created screenshot directory at: {screenshot_dir.absolute()}")
        except Exception as e:
            print(f"Error creating directories: {e}")
            raise

    def _init_twitter_v2(self) -> tweepy.Client:
        """Initialize Twitter API v2 client"""
        return tweepy.Client(
            bearer_token=self.config.twitter_bearer_token,
            consumer_key=self.config.twitter_api_key,
            consumer_secret=self.config.twitter_api_secret,
            access_token=self.config.twitter_access_token,
            access_token_secret=self.config.twitter_access_token_secret
        )

    def _init_twitter_v1(self) -> tweepy.API:
        """Initialize Twitter API v1.1 with proper permissions"""
        auth = tweepy.OAuth1UserHandler(
            consumer_key=self.config.twitter_api_key,
            consumer_secret=self.config.twitter_api_secret,
            access_token=self.config.twitter_access_token,
            access_token_secret=self.config.twitter_access_token_secret
        )
        return tweepy.API(auth, wait_on_rate_limit=True)

    def _load_posted_urls(self) -> set:
        """Load previously posted URLs from log file"""
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return set(line.split("URL: ")[1].strip() for line in f if "URL: " in line)
        except FileNotFoundError:
            return set()

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
                    
        except Exception as e:
            print(f"Error scraping trending page: {e}")
            return []

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

    def take_screenshot(self, url: str) -> Optional[str]:
        """Capture repository README section screenshot"""
        try:
            screenshot_dir = Path(self.config.screenshot_dir)
            if not screenshot_dir.exists():
                raise FileNotFoundError(f"Screenshot directory {screenshot_dir} does not exist")

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 2000})
                
                try:
                    page.goto(url, timeout=60000)
                    
                    # Wait for README section with multiple fallbacks
                    try:
                        # Try GitHub's new README selector first
                        readme_selector = "#readme .Box-body"
                        page.wait_for_selector(readme_selector, state="visible", timeout=15000)
                    except:
                        # Fallback to older README selector
                        try:
                            readme_selector = "#readme"
                            page.wait_for_selector(readme_selector, state="visible", timeout=10000)
                        except:
                            # Fallback to any markdown body
                            page.wait_for_selector(".markdown-body", state="visible", timeout=10000)
                            readme_selector = ".markdown-body"

                    readme_element = page.locator(readme_selector)
                    
                    # Scroll to README section
                    readme_element.scroll_into_view_if_needed()
                    page.wait_for_timeout(2000)  # Allow scroll and rendering
                    
                    # Get bounding box with padding
                    bbox = readme_element.bounding_box()
                    if bbox:
                        # Add padding to the screenshot
                        padding = 20
                        adjusted_bbox = {
                            "x": max(0, bbox["x"] - padding),
                            "y": max(0, bbox["y"] - padding),
                            "width": bbox["width"] + (padding * 2),
                            "height": bbox["height"] + (padding * 2)
                        }
                        
                        filename = f"{url.split('/')[-1]}_{int(time.time())}.png"
                        screenshot_path = screenshot_dir / filename
                        
                        page.screenshot(
                            path=screenshot_path,
                            clip=adjusted_bbox,
                            type="png",
                            animations="disabled"
                        )
                        return str(screenshot_path)
                        
                except Exception as e:
                    print(f"Error capturing README: {e}")
                    return None
                finally:
                    browser.close()
                    
        except Exception as e:
            print(f"Screenshot failed for {url}: {e}")
            return None

    def post_tweet(self, content: str, repo: Dict, screenshot_path: Optional[str] = None) -> bool:
        """Post tweet with full error diagnostics"""
        try:
            # Validate tweet length
            max_length = 280
            full_content = f"{content}\n🔗 {repo['html_url']}"
            if len(full_content) > max_length:
                content = content[:max_length - len(full_content) + len(content) - 3] + "..."

            media_ids = []
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    print(f"Attempting media upload: {screenshot_path}")
                    media = self.twitter_client_v1.media_upload(
                        filename=screenshot_path,
                        media_category="tweet_image"
                    )
                    media_ids.append(media.media_id)
                    print(f"Media uploaded successfully: {media.media_id}")
                except tweepy.TweepyException as e:
                    print(f"Media upload failed: {str(e)}")
                    print(f"API Error Code: {e.api_code}")
                    print(f"API Message: {e.api_messages}")
                    return False

            try:
                tweet_params = {
                    "text": content,
                    "media_ids": media_ids or None
                }
                print(f"Posting tweet with params: {tweet_params}")
                tweet = self.twitter_client_v2.create_tweet(**tweet_params)
                
                if tweet.errors:
                    print(f"Twitter API Errors: {tweet.errors}")
                    return False

                print(f"Successfully posted tweet ID: {tweet.data['id']}")
                return True

            except tweepy.TweepyException as e:
                print(f"Twitter API Error: {str(e)}")
                print(f"API Code: {e.api_code}")
                print(f"API Messages: {e.api_messages}")
                
                if 403 in e.api_codes:
                    print("\n🔴 Critical Permission Issue 🔴")
                    print("1. REQUIRED: Apply for Elevated access at:")
                    print("   https://developer.twitter.com/en/portal/products/elevated")
                    print("2. In App permissions, enable:")
                    print("   - Read & Write")
                    print("   - Media upload")
                    print("3. Regenerate ALL tokens after making changes")
                    print("4. Update your .env file with new tokens")
                
                return False

        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return False
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                os.remove(screenshot_path)

    def _log_success(self, repo: Dict, content: str, screenshot_path: Optional[str]):
        """Log successful post"""
        log_entry = (
            f"\n[{time.ctime()}] Posted: {repo['html_url']}\n"
            f"Content: {content}\n"
            f"Screenshot: {screenshot_path or 'None'}\n"
            f"{'-'*50}"
        )
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
        self.posted_urls.add(repo['html_url'])

    def run(self):
        """Main execution loop"""
        print("Starting RepoTweetBot...")
        while True:
            try:
                projects = self.fetch_github_projects()
                if not projects:
                    print("No projects fetched, retrying in 5 minutes...")
                    time.sleep(300)
                    continue

                new_projects = [p for p in projects if p['html_url'] not in self.posted_urls]
                if not new_projects:
                    print("No new projects found, refreshing in 1 hour...")
                    time.sleep(3600)
                    continue

                repo = random.choice(new_projects)
                print(f"Selected repository: {repo['html_url']}")

                # Generate content and try to get screenshot
                tweet_content = self.generate_tweet_content(repo)
                try:
                    screenshot_path = self.take_screenshot(repo['html_url'])
                except Exception as e:
                    print(f"Screenshot failed, continuing without image: {e}")
                    screenshot_path = None

                if self.post_tweet(tweet_content, repo, screenshot_path):
                    print(f"Successfully posted: {repo['html_url']}")
                    time.sleep(self.sleep_interval)
                else:
                    print("Posting failed, retrying in 10 minutes...")
                    time.sleep(600)

            except Exception as e:
                print(f"Critical error: {e}")
                time.sleep(600)

def main():
    """Entry point with configuration setup"""
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