# Putting the dashboard online

The dashboard is a Streamlit (Python) application, so it needs a Python server. GitHub Pages only serves static files, so the setup has three parts:

| Part | Service | Address |
|---|---|---|
| Source code | GitHub repository | `https://github.com/trustsims/Sino-Africa-Trade-Intelligence` |
| Live dashboard (read-only demo) | Streamlit Community Cloud (free) | `https://<app-name>.streamlit.app` |
| Project page with screenshots and links | GitHub Pages, from the `docs/` folder | `https://trustsims.github.io/Sino-Africa-Trade-Intelligence/` |

The online copy imports the four UN Comtrade files in `data/raw/` automatically on first start (about a minute) and runs in read-only mode: visitors can use every analysis page, but cannot upload, import or delete data.

## 1. Names used

- GitHub repository: `https://github.com/trustsims/Sino-Africa-Trade-Intelligence`
- App name on Streamlit Community Cloud: `sino-africa-trade-intelligence` (already filled into `docs/index.html`). If that name is taken, choose another and change it in `docs/index.html`.

## 2. Put the project on GitHub

1. Sign in at https://github.com and click **New repository**. Name it `Sino-Africa-Trade-Intelligence`, choose **Public**, and do **not** add a README, .gitignore or licence.
2. In the VS Code terminal, inside `C:\Projects\Sino-Africa-Trade-Intelligence`, check that the four data files are present:
   ```powershell
   dir data\raw\*_ag6.csv
   ```
3. If Git has never been used on this computer, set your name and email once:
   ```powershell
   git config --global user.name "Trust Simukonda"
   git config --global user.email "you@example.com"
   ```
4. Commit and push (run one line at a time):
   ```powershell
   git add .
   git commit -m "Dashboard with trade outlook and online demo"
   git branch -M main
   git remote add origin https://github.com/trustsims/Sino-Africa-Trade-Intelligence.git
   git push -u origin main
   ```
   If `git remote add` says the remote already exists, use `git remote set-url origin <the same URL>` instead. A browser window may ask you to sign in to GitHub the first time.

The `.gitignore` file keeps the database, the virtual environment, logs and your `.env` file out of GitHub.

## 3. Deploy the live dashboard

1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Repository: `trustsims/Sino-Africa-Trade-Intelligence`; Branch: `main`; Main file path: `app.py`.
4. App URL: type your app name, e.g. `sino-africa-trade-intelligence`.
5. Open **Advanced settings**:
   - Python version: **3.13** (or the newest offered).
   - Secrets: paste exactly
     ```toml
     TRADE_AUTOLOAD = "1"
     TRADE_READ_ONLY = "1"
     ```
6. Click **Deploy**. Installing the packages takes a few minutes; the first page load then imports the data (about a minute). After that, pages open in a few seconds.

Free apps go to sleep after some days without visitors. Anyone who opens the link can wake the app with one click; it then imports the data again.

## 4. Publish the project page

1. On GitHub, open the repository → **Settings** → **Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**, branch **main**, folder **/docs**, and click **Save**.
3. After a minute or two the page is live at `https://trustsims.github.io/Sino-Africa-Trade-Intelligence/`.

## 5. Updating later

After changing code or data on your computer:

```powershell
git add .
git commit -m "Describe the change"
git push
```

Streamlit Community Cloud and GitHub Pages both update automatically after a push.

## Running the demo mode locally

To see exactly what visitors will see, start the app with the same settings:

```powershell
$env:TRADE_AUTOLOAD="1"; $env:TRADE_READ_ONLY="1"; python -m streamlit run app.py
```
