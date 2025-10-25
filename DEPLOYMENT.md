# Deployment Guide

This guide will help you deploy the AYO Venue Scraper web application to free hosting platforms.

## Prerequisites
- Git repository (push your code to GitHub, GitLab, or Bitbucket)
- Account on your chosen hosting platform

## Option 1: Deploy to Render.com (Recommended)

Render offers a free tier perfect for this application.

1. **Sign up** at [render.com](https://render.com)
2. **Create a new Web Service**
   - Click "New +" → "Web Service"
   - Connect your Git repository
   - Select the repository containing this code
3. **Configure the service**
   - Name: `ayo-venue-scraper`
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Instance Type: `Free`
4. **Click "Create Web Service"**
5. Wait for deployment (usually 2-5 minutes)
6. Your app will be live at `https://your-app-name.onrender.com`

### Note on Free Tier Limitations
- The free tier spins down after 15 minutes of inactivity
- First request after spin-down may take 30-60 seconds
- Selenium may not work on free tier due to memory constraints (use API mode instead)

## Option 2: Deploy to Railway.app

Railway also offers a generous free tier.

1. **Sign up** at [railway.app](https://railway.app)
2. **Create a new project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository
3. **Configure deployment**
   - Railway auto-detects Python and uses the Procfile
   - No additional configuration needed
4. **Generate a domain**
   - Go to Settings → Generate Domain
5. Your app will be live at `https://your-app-name.up.railway.app`

## Option 3: Deploy to Fly.io

Fly.io offers free tier with better resources.

1. **Install flyctl** CLI: `curl -L https://fly.io/install.sh | sh`
2. **Sign up/Login**: `fly auth signup` or `fly auth login`
3. **Launch your app**: `fly launch`
   - Choose app name
   - Choose region
   - Don't add PostgreSQL/Redis
4. **Deploy**: `fly deploy`
5. Your app will be live at `https://your-app-name.fly.dev`

## Running Locally

To test the application locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Flask development server
python app.py

# Or use gunicorn (production server)
gunicorn app:app
```

Visit `http://localhost:5000` in your browser.

## Environment Variables

You can set these environment variables in your hosting platform:

- `PORT` - Port number (usually set automatically by the platform)
- `PYTHON_VERSION` - Python version (3.11.0 recommended)

## Troubleshooting

### Selenium Not Working
- Use API mode instead (`use_api=True` checkbox in the web interface)
- Selenium requires Chrome/Chromium which may not be available on free tiers

### Memory Issues
- Reduce `max_pages` to 1-2
- Use `max_venues` to limit the number of venues scraped
- Enable `use_api` mode (less memory intensive)

### Slow Response Times
- This is normal for web scraping
- The scraper may take 1-5 minutes depending on settings
- Free tier instances may be slower

## Best Practices

1. **Use API Mode**: Enable "Use API for slot data" for faster and more reliable scraping
2. **Limit Scope**: Use `max_pages` and `max_venues` to prevent timeouts
3. **Monitor Usage**: Most free tiers have usage limits (bandwidth, build minutes, etc.)
4. **Keep Alive** (optional): Use a service like UptimeRobot to ping your app every 5 minutes to prevent spin-down

## Support

If you encounter issues:
1. Check the deployment logs in your hosting platform
2. Verify all dependencies are installed
3. Test locally first before deploying

Happy scraping!
