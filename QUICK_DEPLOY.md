# ⚡ 5-Minute Deployment Guide

## 🎯 Deploy to Render (100% Free)

### Step 1: Push to GitHub (2 minutes)

```bash
# In your terminal, from the ayo-scrape directory:

# Add all files
git add .

# Commit
git commit -m "Ready for deployment with rate limiting"

# Push to GitHub
git push origin main
```

> **Don't have a GitHub repo yet?**
> 1. Go to [github.com/new](https://github.com/new)
> 2. Create repository (name: `ayo-scrape`)
> 3. Then run:
> ```bash
> git remote add origin https://github.com/YOUR_USERNAME/ayo-scrape.git
> git branch -M main
> git push -u origin main
> ```

### Step 2: Deploy on Render (3 minutes)

1. **Go to:** [render.com](https://render.com)
2. **Sign up** with GitHub (free!)
3. **New +** → **Web Service**
4. **Connect** your `ayo-scrape` repo
5. **Settings:**
   - ✅ Use default settings (we configured them!)
   - ✅ Click **"Create Web Service"**
6. **Wait 2-3 minutes** ⏳
7. **Done!** 🎉

Your app will be live at:
```
https://ayo-venue-scraper.onrender.com
```

---

## 🔥 That's It!

### What You Get:
- ✅ Live scraper at a public URL
- ✅ Auto-deploys when you push to GitHub
- ✅ Free forever (Render free tier)
- ✅ HTTPS included
- ✅ Custom domain support (optional)

### Share Your App:
```
Your Live URL: https://YOUR-APP.onrender.com

Features:
✅ Real-time scraping progress
✅ 30-second rate limit per user
✅ Beautiful countdown timer
✅ Shows hours & prices
```

---

## ⚠️ Important Notes

1. **First Load Slow?**
   - Free tier spins down after 15 min
   - First request takes ~30 seconds
   - After that, it's fast!

2. **Auto-Deployment:**
   - Every `git push` triggers new deployment
   - Check Render dashboard for progress

3. **Logs:**
   - View at: Render Dashboard → Your Service → Logs

---

## 🚀 Quick Commands

```bash
# Update your app
git add .
git commit -m "Your update message"
git push

# Render auto-deploys in ~2 minutes!
```

---

## 🎉 You're Done!

Go to your Render URL and start scraping! 🎾
