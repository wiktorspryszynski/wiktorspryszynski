# GitHub ASCII Stats
Automatically generates a **colorful ASCII art image** of your GitHub stats and updates your `README.md` daily via GitHub Actions.

## Credits
I got the inspiration from [Andrew6rant's repo](https://github.com/Andrew6rant/Andrew6rant). Please check him out!

---

## Setup

### 1️⃣ Clone repo

```bash
git clone https://github.com/your_username/your_repo.git
cd your_repo
```

### 2️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

**requirements.txt:**

``` 
requests
pyfiglet
pillow
```

### 3️⃣ Create Fine-grained GitHub token

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token  
2. **Repository access:** All repositories → Read-only  
3. **Permissions:** Contents → Read-only, Metadata → Read-only  
4. Optional: No expiration  
5. Copy the token

### 4️⃣ Add token to repository secrets

- Settings → Secrets and variables → Actions → New repository secret  
- Name: ```GH_TOKEN```  
- Paste token

### 5️⃣ Configure Python script

Edit `generate_readme.py`:

```python
USERNAME = "your_github_username"
BIRTHDAY_DAY, BIRTHDAY_MONTH, BIRTHDAY_YEAR = x, y, z
```

Script will fetch your stats, generate ASCII art PNG, and update `README.md`.

### 6️⃣ GitHub Actions

Workflow file: `.github/workflows/update_readme.yml`  
Runs daily or manually via `workflow_dispatch`. No extra config needed if `GH_TOKEN` secret exists.

---

README will show the generated image:

``` 
![My GitHub Stats](ascii_stats.png)

_Last update: YYYY-MM-DD HH:MM:SS UTC_
```

Optional: change font in `pyfiglet` or colors in the Python script.