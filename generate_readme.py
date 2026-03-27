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
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
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
    required_keys = {"active_days_this_year", "current_year_day", "languages", "fetched_at"}
    if cached and required_keys.issubset(cached):
        return cached, True
    raw = run_query(QUERY, {"login": USERNAME})["user"]
    stats = build_stats(raw)
    save_cache(stats)
    return stats, False


def build_stats(user: dict) -> dict:
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"] or {}

    weeks = calendar.get("weeks") or []
    now_utc = datetime.now(timezone.utc)
    current_year = now_utc.year
    current_year_day = now_utc.timetuple().tm_yday
    active_days = sum(
        1
        for week in weeks
        for day in week.get("contributionDays", [])
        if day.get("contributionCount", 0) > 0 and day.get("date", "").startswith(f"{current_year}-")
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
        "repos": user["repositories"]["totalCount"],
        "repos_with_commits": contributions["totalRepositoriesWithContributedCommits"],
        "lines_added": additions,
        "lines_removed": deletions,
        "net_lines": additions - deletions,
        "merged_prs": merged_prs,
        "active_days_this_year": active_days,
        "current_year_day": current_year_day,
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


def format_datetime(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_uptime_since_birthday() -> str:
    birthday = datetime(2000, 5, 31, tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if now_utc < birthday:
        return "not started"

    delta = now_utc - birthday
    total_seconds = int(delta.total_seconds())
    total_days = delta.days
    years = total_days // 365
    days = total_days % 365
    hours = (total_seconds % 86400) // 3600
    return f"{years}y {days}d {hours}h"


def make_row(label: str, value: str, width: int = 68) -> str:
    inner_width = width
    left = f"{label} "
    if len(left) + len(value) > inner_width:
        trim_to = max(1, inner_width - len(value) - 1)
        left = f"{label[:trim_to]} "
    dots = "." * max(1, inner_width - len(left) - len(value) - 1)
    return f"{left}{dots} {value}"


def make_title(title: str, width: int = 68) -> str:
    return f" {title} ".center(width, "-")


def render_image(stats: dict, cached: bool) -> None:
    # 3 customizable terminal accent colors (white is separate base text color).
    COLOR_BG = (8, 16, 20)
    COLOR_WHITE = (232, 241, 247)
    COLOR_TEAL = (45, 212, 191)
    COLOR_GREEN = (134, 239, 172)
    COLOR_RED = (248, 113, 113)

    FONT_SIZE = 16
    ROW_WIDTH = 68
    PADDING_X = 26
    PADDING_Y = 22

    font = load_font(FONT_SIZE)
    probe = Image.new("RGB", (10, 10), COLOR_BG)
    probe_draw = ImageDraw.Draw(probe)
    char_box = probe_draw.textbbox((0, 0), "M", font=font)
    line_box = probe_draw.textbbox((0, 0), "Mg", font=font)
    char_width = char_box[2] - char_box[0]
    line_height = (line_box[3] - line_box[1]) + 6

    cache_tag = "cached" if cached else "fresh"
    lines: list[tuple[str, tuple[int, int, int], str | None, tuple[int, int, int] | None]] = [
        (make_title("ABOUT ME", ROW_WIDTH), COLOR_TEAL, None, None),
        (make_row("Name", stats["display_name"], ROW_WIDTH), COLOR_WHITE, None, None),
        (make_row("Uptime", format_uptime_since_birthday(), ROW_WIDTH), COLOR_WHITE, None, None),
        ("", COLOR_WHITE, None, None),
        (make_title("GITHUB INFO", ROW_WIDTH), COLOR_GREEN, None, None),
        (make_row("Commits (year)", format_number(stats["total_commits"]), ROW_WIDTH), COLOR_WHITE, None, None),
        (make_row("Public repos", format_number(stats["repos"]), ROW_WIDTH), COLOR_WHITE, None, None),
        (
            make_row("Lines added", f"++ {format_number(stats['lines_added'])}", ROW_WIDTH),
            COLOR_WHITE,
            f"++ {format_number(stats['lines_added'])}",
            COLOR_GREEN,
        ),
        (
            make_row("Lines removed", f"-- {format_number(stats['lines_removed'])}", ROW_WIDTH),
            COLOR_WHITE,
            f"-- {format_number(stats['lines_removed'])}",
            COLOR_RED,
        ),
        (make_row("Net lines", f"{stats['net_lines']:+,}", ROW_WIDTH), COLOR_WHITE, None, None),
        (
            make_row("Active days (this year)", f"{stats['active_days_this_year']} / {stats['current_year_day']}", ROW_WIDTH),
            COLOR_WHITE,
            None,
            None,
        ),
        (make_row("Contributions", format_number(stats["total_contributions"]), ROW_WIDTH), COLOR_WHITE, None, None),
        ("", COLOR_WHITE, None, None),
        (make_title("TOP LANGUAGES", ROW_WIDTH), COLOR_RED, None, None),
    ]

    if stats["languages"]:
        for language in stats["languages"]:
            lang_value = f"{language['percent']:.1f}%"
            lines.append((make_row(language["name"], lang_value, ROW_WIDTH), COLOR_WHITE, None, None))
    else:
        lines.append((make_row("Languages", "No data", ROW_WIDTH), COLOR_WHITE, None, None))

    image_width = int((PADDING_X * 2) + (ROW_WIDTH * char_width))
    image_height = int((PADDING_Y * 2) + (line_height * len(lines)))
    image = Image.new("RGB", (image_width, image_height), COLOR_BG)
    draw = ImageDraw.Draw(image)

    y = PADDING_Y
    for text, color, highlight_text, highlight_color in lines:
        draw.text((PADDING_X, y), text, font=font, fill=color)
        if highlight_text and highlight_color:
            highlight_index = text.rfind(highlight_text)
            if highlight_index >= 0:
                draw.text((PADDING_X + (highlight_index * char_width), y), highlight_text, font=font, fill=highlight_color)
        y += line_height

    image.save(IMAGE_PATH)


def update_readme(stats: dict, cached: bool) -> None:
    cache_tag = "yes" if cached else "no"
    readme_content = (
        f"# Hi, I'm {stats['display_name']}\n\n"
        "## GitHub summary (generated PNG)\n\n"
        f"![GitHub summary]({IMAGE_PATH.name})\n\n"
        f"_Last updated: {format_datetime(stats['fetched_at'])} UTC - cached: {cache_tag}_\n"
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
