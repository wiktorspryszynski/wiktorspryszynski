import os
import requests
from pyfiglet import figlet_format
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# --- CONFIG ---
USERNAME = "wiktorspryszynski"
TOKEN = os.environ["GH_TOKEN"]

GRAPHQL_URL = "https://api.github.com/graphql"

# --- FETCH DATA FROM GRAPHQL ---
query = """
{
  user(login: "%s") {
    contributionsCollection {
      totalCommitContributions
    }
    repositories(first: 50, orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
    }
  }
}
""" % USERNAME

headers = {"Authorization": f"Bearer {TOKEN}"}
r = requests.post(GRAPHQL_URL, json={"query": query}, headers=headers)
data = r.json()

total_commits = data["data"]["user"]["contributionsCollection"]["totalCommitContributions"]
total_repos = data["data"]["user"]["repositories"]["totalCount"]

# --- CREATE ASCII ART ---
ascii_text = figlet_format("MY STATS", font="slant")
stats_text = f"Total commits: {total_commits}\nTotal repos: {total_repos}\nLast updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
full_text = ascii_text + "\n" + stats_text

# --- CREATE IMAGE ---
lines = full_text.split("\n")
width = max(len(line) for line in lines) * 12
height = len(lines) * 20

img = Image.new("RGB", (width, height), color="black")
draw = ImageDraw.Draw(img)
font = ImageFont.load_default()

# Gradient colors
colors = [(255,0,0), (255,165,0), (255,255,0), (0,255,0), (0,0,255), (75,0,130), (238,130,238)]

for i, line in enumerate(lines):
    color = colors[i % len(colors)]
    draw.text((0, i*20), line, fill=color, font=font)

img_path = "ascii_stats.png"
img.save(img_path)

# --- WRITE README.md ---
readme_content = f"""# My GitHub Stats

![My GitHub Stats]({img_path})

_Last update: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}_  
"""

with open("README.md", "w", encoding="utf-8") as f:
    f.write(readme_content)

print("README.md updated!")