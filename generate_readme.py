import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

USERNAME = "wiktorspryszynski"
GRAPHQL_URL = "https://api.github.com/graphql"
IMAGE_PATH = Path("profile_summary.png")
CACHE_PATH = Path("cache/github_stats.json")
CACHE_TTL_SECONDS = 60 * 60  # keep cached payload for one hour
TOKEN = os.environ.get("GH_TOKEN")
LOCAL_FONT_PATH = "./fonts/CascadiaCode.ttf"

if not TOKEN:
    raise SystemExit("GH_TOKEN environment variable must be set before running this script.")

QUERY = """
query ($login: String!) {
  user(login: $login) {
    name
    login
    repositories(privacy: PUBLIC, ownerAffiliations: OWNER, first: 50, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
          }
        }
      }
      pullRequestContributionsByRepository(maxRepositories: 50) {
        contributions(first: 100) {
          nodes {
            pullRequest {
              additions
              deletions
              merged
            }
          }
        }
      }
    }
  }
}
"""


def run_query(query: str, variables: dict) -> dict:
    response = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise SystemExit(f"GitHub GraphQL error: {payload['errors']}")
    return payload["data"]


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
    except (ValueError, KeyError):
        return None
    if datetime.now(timezone.utc) - fetched_at <= timedelta(seconds=CACHE_TTL_SECONDS):
        return payload["data"]
    return None


def save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": data["fetched_at"], "data": data}
    CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_stats() -> tuple[dict, bool]:
    cached = load_cache()
    if cached:
        return cached, True
    raw = run_query(QUERY, {"login": USERNAME})["user"]
    stats = build_stats(raw)
    save_cache(stats)
    return stats, False


def build_stats(user: dict) -> dict:
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"] or {}

    weeks = calendar.get("weeks") or []
    active_days = sum(
        1
        for week in weeks
        for day in week.get("contributionDays", [])
        if day.get("contributionCount", 0) > 0
    )

    additions = deletions = merged_prs = 0
    for repo in contributions.get("pullRequestContributionsByRepository", []):
        for node in repo.get("contributions", {}).get("nodes", []):
            pr = node.get("pullRequest")
            if not pr:
                continue
            additions += pr.get("additions") or 0
            deletions += pr.get("deletions") or 0
            if pr.get("merged"):
                merged_prs += 1

    language_totals: dict[str, int] = {}
    for repo in user["repositories"]["nodes"]:
        for edge in (repo.get("languages") or {}).get("edges", []):
            name = edge["node"]["name"]
            language_totals[name] = language_totals.get(name, 0) + (edge.get("size") or 0)

    total_bytes = sum(language_totals.values())
    sorted_languages = sorted(language_totals.items(), key=lambda item: item[1], reverse=True)
    languages = []
    seen_bytes = 0
    for name, byte_count in sorted_languages[:4]:
        languages.append(
            {
                "name": name,
                "bytes": byte_count,
                "percent": byte_count * 100 / total_bytes if total_bytes else 0,
            }
        )
        seen_bytes += byte_count
    if total_bytes and seen_bytes < total_bytes:
        other_bytes = total_bytes - seen_bytes
        languages.append(
            {
                "name": "Other",
                "bytes": other_bytes,
                "percent": other_bytes * 100 / total_bytes,
            }
        )

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    return {
        "display_name": user.get("name") or user["login"],
        "total_commits": contributions["totalCommitContributions"],
        "total_prs": contributions["totalPullRequestContributions"],
        "total_issues": contributions["totalIssueContributions"],
        "repos": user["repositories"]["totalCount"],
        "repos_with_commits": contributions["totalRepositoriesWithContributedCommits"],
        "lines_added": additions,
        "lines_removed": deletions,
        "net_lines": additions - deletions,
        "merged_prs": merged_prs,
        "active_days": active_days,
        "total_contributions": calendar.get("totalContributions", 0),
        "languages": languages,
        "fetched_at": fetched_at,
    }


def format_number(value: int) -> str:
    return f"{value:,}"


def load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(LOCAL_FONT_PATH, size)
    except OSError:
        raise RuntimeError(f"Could not load font from {LOCAL_FONT_PATH}. Make sure the file exists and is a valid TTF font.")


def render_image(stats: dict, cached: bool) -> None:
    width, height = 1200, 680
    background = (15, 23, 42)
    text_color = (226, 232, 240)
    accent_color = (248, 113, 113)

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    heading_font = load_font(48)
    stat_font = load_font(36)
    small_font = load_font(22)

    title = f"{stats['display_name']}'s GitHub summary"
    draw.text((40, 40), title, font=heading_font, fill=text_color)
    draw.rectangle((40, 98, width - 40, 102), fill=accent_color)

    stat_items = [
        ("Commits (year)", format_number(stats["total_commits"])),
        ("Public repos", format_number(stats["repos"])),
        ("Pull requests", format_number(stats["total_prs"])),
        ("Merged PRs", format_number(stats["merged_prs"])),
        ("Issues opened", format_number(stats["total_issues"])),
        ("Repos with commits", format_number(stats["repos_with_commits"])),
        ("Lines added", f"+{format_number(stats['lines_added'])}"),
        ("Lines removed", f"-{format_number(stats['lines_removed'])}"),
        ("Net lines", f"{stats['net_lines']:+,}"),
        ("Active days", f"{stats['active_days']} / 365"),
        ("Contributions", format_number(stats["total_contributions"])),
    ]

    x_label = 40
    x_value = 440
    y = 130
    for label, value in stat_items:
        draw.text((x_label, y), label, font=stat_font, fill=text_color)
        draw.text((x_value, y), value, font=stat_font, fill=accent_color)
        y += 46

    lang_x = 640
    lang_y = 140
    draw.text((lang_x, 130), "Top languages", font=stat_font, fill=text_color)
    bar_start = lang_x
    bar_width = 420
    bar_height = 18
    gap = 50
    if stats["languages"]:
        for index, language in enumerate(stats["languages"]):
            line_y = lang_y + gap * index
            draw.text((lang_x, line_y), f"{language['name']}", font=stat_font, fill=text_color)
            percent_text = f"{language['percent']:.1f}%"
            draw.text((lang_x + bar_width + 20, line_y), percent_text, font=stat_font, fill=accent_color)
            bar_y = line_y + 35
            fill_width = int(bar_width * (language["percent"] / 100))
            draw.rectangle(
                (bar_start, bar_y, bar_start + bar_width, bar_y + bar_height),
                outline=text_color,
            )
            if fill_width:
                draw.rectangle(
                    (bar_start, bar_y, bar_start + fill_width, bar_y + bar_height),
                    fill=accent_color,
                )
    else:
        draw.text((lang_x, lang_y + 20), "Language data not available", font=stat_font, fill=text_color)

    cache_tag = "cached" if cached else "fresh"
    draw.text(
        (40, height - 40),
        f"Last refreshed: {stats['fetched_at']} UTC - cache: {cache_tag}",
        font=small_font,
        fill=text_color,
    )

    image.save(IMAGE_PATH)


def update_readme(stats: dict, cached: bool) -> None:
    cache_tag = "yes" if cached else "no"
    readme_content = (
        f"# Hi, I'm {stats['display_name']}\n\n"
        "## GitHub summary (generated PNG)\n\n"
        f"![GitHub summary]({IMAGE_PATH.name})\n\n"
        f"_Last updated: {stats['fetched_at']} UTC - cached: {cache_tag}_\n"
    )
    Path("README.md").write_text(readme_content, encoding="utf-8")


def main() -> None:
    stats, cached = get_stats()
    render_image(stats, cached)
    update_readme(stats, cached)
    message = "Using cached data" if cached else "Fetched new data"
    print(f"README.md and {IMAGE_PATH.name} refreshed ({message}).")


if __name__ == "__main__":
    main()
