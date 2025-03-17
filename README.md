# X-OS Newsletter Bot 🤖

A smart Twitter bot that automatically discovers and shares trending open-source projects from GitHub. Built with Python and powered by Ollama's AI.

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 🌟 Features

- 🤖 Automated discovery of trending GitHub repositories
- 🎯 Smart content generation using Ollama AI
- 📸 Automatic README screenshot capture
- 🌐 Language detection to filter non-English content
- ⏰ Natural posting schedule with randomized intervals
- 🔄 Intelligent rate limit handling
- 📊 Detailed logging and monitoring
- 🛡️ Duplicate post prevention
- 🌙 Smart scheduling during active hours (9 AM - 11 PM)

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Twitter Developer Account with API access
- Ollama installed locally
- Playwright for screenshot capture

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/x-os-newsletter.git
cd x-os-newsletter
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
```
Edit `.env` with your credentials:
```env
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token
POSTS_PER_HOUR=4
OLLAMA_MODEL=deepseek-coder
```

4. Install Playwright browsers:
```bash
playwright install
```

### Usage

Run the bot:
```bash
python twitter_oss_bot.py
```

For production deployment, use the systemd service:
```bash
sudo cp twitter_bot.service /etc/systemd/system/
sudo systemctl enable twitter_bot
sudo systemctl start twitter_bot
```

## 🛠️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TWITTER_API_KEY` | Twitter API Key | Yes |
| `TWITTER_API_SECRET` | Twitter API Secret | Yes |
| `TWITTER_ACCESS_TOKEN` | Twitter Access Token | Yes |
| `TWITTER_ACCESS_TOKEN_SECRET` | Twitter Access Token Secret | Yes |
| `TWITTER_BEARER_TOKEN` | Twitter Bearer Token | Yes |
| `POSTS_PER_HOUR` | Number of posts per hour | No (default: 4) |
| `OLLAMA_MODEL` | Ollama model to use | No (default: deepseek-coder) |

### Posting Schedule

- Active hours: 9 AM - 11 PM
- Random delays between posts: 45-120 minutes
- 80% chance to skip during off-hours
- 10% random skip chance during active hours

## 📝 Logging

Logs are stored in `generated_tweets.log` with detailed information about:
- Posted tweets
- Rate limits
- Screenshot captures
- Error messages

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Tweepy](https://github.com/tweepy/tweepy) for Twitter API integration
- [Ollama](https://github.com/ollama/ollama) for AI-powered content generation
- [Playwright](https://github.com/microsoft/playwright) for screenshot capture
- [Langdetect](https://github.com/Mimino666/langdetect) for language detection

## 📞 Support

If you encounter any issues or have questions, please:
1. Check the [Issues](https://github.com/yourusername/x-os-newsletter/issues) page
2. Create a new issue if needed
3. Join our [Discussions](https://github.com/yourusername/x-os-newsletter/discussions)

## 🔄 Roadmap

- [ ] Add support for multiple social media platforms
- [ ] Implement custom content templates
- [ ] Add analytics dashboard
- [ ] Support for custom posting schedules
- [ ] Enhanced error recovery mechanisms

## 📊 Project Status

![GitHub last commit](https://img.shields.io/github/last-commit/yourusername/x-os-newsletter)
![GitHub issues](https://img.shields.io/github/issues/yourusername/x-os-newsletter)
![GitHub pull requests](https://img.shields.io/github/issues-pr/yourusername/x-os-newsletter)

```bash
# Copy the service file
sudo cp twitter_bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable twitter_bot

# Start the service
sudo systemctl start twitter_bot
```

### Check Service Status

```bash
sudo systemctl status twitter_bot
```

### Check Logs

```bash
sudo journalctl -u twitter_bot -f

# Check specific logs
sudo journalctl -u twitter_bot -f -n 100
```

### Stop Service

```bash
sudo systemctl stop twitter_bot
```

### Disable Service

```bash
sudo systemctl disable twitter_bot
```

### Remove Service

```bash
sudo rm /etc/systemd/system/twitter_bot.service
```
