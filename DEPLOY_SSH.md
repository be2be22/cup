# راهنمای دیپلوی روی alwaysdata از طریق SSH + GitHub

این راهنما فرض می‌کنه کد توی ریپازیتوری گیت‌هاب `be2be22/cup` هست و شما
می‌خواید از طریق SSH وصل بشید به سرور alwaysdata و فایل‌ها رو از اونجا بگیرید
یا آپدیت کنید.

## ۰. پیش‌نیاز: اطلاعات SSH خودتون
از پنل alwaysdata → **SSH access** آدرس و پورت SSH حساب‌تون رو پیدا کنید
(چیزی شبیه `ssh USERNAME@ssh-USERNAME.alwaysdata.net`).

## ۱. اتصال به سرور
```bash
ssh USERNAME@ssh-USERNAME.alwaysdata.net
```
رمز عبور حساب alwaysdata‌تون رو می‌پرسه (یا اگه کلید SSH ست کرده باشید، بدون رمز وصل می‌شه).

## ۲. کلون کردن ریپازیتوری (اولین بار)
```bash
cd ~
git clone https://github.com/be2be22/cup.git worldcup
```
اگه ریپازیتوری private باشه و در آینده توکن قبلی رو باطل کرده باشید، باید یه
[Personal Access Token جدید](https://github.com/settings/tokens) بسازید و به‌جای
رمز عبور توی این دستور استفاده کنید:
```bash
git clone https://YOUR_NEW_TOKEN@github.com/be2be22/cup.git worldcup
```

بعد از کلون، پوشه‌ی پروژه دقیقاً همون چیزیه که کران و سایت وبهوک ازش استفاده
می‌کنن (یعنی `~/worldcup/scripts/main_monitor.py` و `~/worldcup/webhook.py`).

⚠️ اگه ریپو رو با توکنی که مستقیم توی URL بود کلون کردید، اون توکن توی
`git remote -v` و توی تاریخچه‌ی شل ذخیره می‌مونه. بعد از کلون بهتره:
```bash
git remote set-url origin https://github.com/be2be22/cup.git
```
تا توکن از remote URL پاک بشه (برای پوش کردن‌های بعدی دوباره می‌خواد وارد بشه، یا از SSH key استفاده کنید).

## ۳. آپدیت کردن کد در آینده (بعد از هر تغییر توی گیت‌هاب)
```bash
cd ~/worldcup
git pull origin main
```
همین! چون کران هر بار مستقیم از روی همین فایل‌ها اجرا می‌شه، لازم نیست چیز
دیگه‌ای ری‌استارت بشه. برای سایت وبهوک (WSGI) هم معمولاً بعد از `git pull`
کافیه یا خودش تغییر رو می‌گیره یا از پنل روی همون سایت گزینه‌ی **Restart** رو بزنید.

## ۴. تنظیم متغیرهای محیطی / local_settings.py
این مقادیر عمداً از طریق `git pull` نمی‌آن (نباید توی گیت باشن). دو راه:

- اگه پنل alwaysdata روی سایت شما بخش Environment variables واقعی داره:
  از اونجا تنظیم کنید.
- در غیر این صورت (یا برای راحتی)، همین‌جا روی سرور بسازیدش:
  ```bash
  cat > ~/worldcup/local_settings.py << 'EOF'
  TELEGRAM_BOT_TOKEN = "..."
  TELEGRAM_WEBHOOK_SECRET = "..."
  AI_API_BASE_URL = "..."
  AI_API_KEY = "..."
  AI_MODEL = "oc/mimo-v2.5-free"
  EOF
  ```
  این فایل توی `.gitignore` هست، پس با `git pull` بعدی پاک/بازنویسی نمی‌شه و
  هیچ‌وقت به گیت‌هاب پوش نمی‌شه.

## ۵. تست بعد از هر دیپلوی
```bash
cd ~/worldcup
python3 scripts/check_setup.py
```

## ۶. ثبت/آپدیت وبهوک (فقط وقتی آدرس سایت وبهوک عوض بشه)
```bash
cd ~/worldcup
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_WEBHOOK_SECRET=...   # اگه تنظیم کردید
python3 scripts/set_webhook.py https://bot.yourdomain.alwaysdata.net/
```

## خلاصه‌ی گردش‌کار روزانه
1. کد رو محلی یا توی چت تغییر بدید → پوش به گیت‌هاب.
2. `ssh` به alwaysdata → `cd ~/worldcup && git pull origin main`.
3. اگه فقط `scripts/` یا `lib/` عوض شده، کران خودش دفعه‌ی بعد از کد جدید
   استفاده می‌کنه؛ اگه `webhook.py` عوض شده، سایت وبهوک رو از پنل Restart کنید.
