import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

USERNAME = "wiktorspryszynski"
BIRTHDAY_DAY, BIRTHDAY_MONTH, BIRTHDAY_YEAR = 31, 5, 2000
BIRTHDAY = datetime(BIRTHDAY_YEAR, BIRTHDAY_MONTH, BIRTHDAY_DAY, tzinfo=timezone.utc)
GRAPHQL_URL = "https://api.github.com/graphql"
IMAGE_PATH = Path("profile_summary.png")
CACHE_PATH = Path("cache/github_stats.json")
FONT_PATH = Path("./fonts/CascadiaCode.ttf")
NOW_DT = datetime.now(timezone.utc)
CACHE_TTL_SECONDS = 60 * 60  # keep cached payload for one hour
TOKEN = os.environ.get("GH_TOKEN")
BIRTHDAY_EMOJI = "\U0001F382"

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
      contributionYears
      totalCommitContributions
      totalPullRequestContributions
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

YEARLY_COMMITS_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
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
    if NOW_DT - fetched_at <= timedelta(seconds=CACHE_TTL_SECONDS):
        return payload["data"]
    return None


def save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": data["fetched_at"], "data": data}
    CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_stats() -> tuple[dict, bool]:
    cached = load_cache()
    required_keys = {"active_days", "total_commits_all_time", "languages", "fetched_at"}
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
    NOW_DT = datetime.now(timezone.utc)
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

    total_commits_all_time = 0
    for year in contributions.get("contributionYears", []):
        from_dt = f"{year}-01-01T00:00:00Z"
        to_dt = f"{year}-12-31T23:59:59Z"
        year_data = run_query(
            YEARLY_COMMITS_QUERY,
            {"login": USERNAME, "from": from_dt, "to": to_dt},
        )
        total_commits_all_time += year_data["user"]["contributionsCollection"]["totalCommitContributions"]

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

    fetched_at = NOW_DT.replace(microsecond=0).isoformat()

    return {
        "display_name": user.get("name") or user["login"],
        "total_commits": contributions["totalCommitContributions"],
        "total_commits_all_time": total_commits_all_time,
        "total_prs": contributions["totalPullRequestContributions"],
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
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        raise RuntimeError(f"Could not load font from {FONT_PATH}. Make sure the file exists and is a valid TTF font.")


def load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    candidates = ("seguiemj.ttf", "Segoe UI Emoji", "NotoColorEmoji.ttf")
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return None


def format_datetime(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_uptime_since_birthday() -> str:
    if NOW_DT < BIRTHDAY:
        return "not started"

    now_utc_plus_1 = NOW_DT + timedelta(hours=1)
    birthday_local = BIRTHDAY + timedelta(hours=1)

    years = now_utc_plus_1.year - birthday_local.year
    if (now_utc_plus_1.month, now_utc_plus_1.day) < (birthday_local.month, birthday_local.day):
        years -= 1

    last_birthday = birthday_local.replace(year=birthday_local.year + years)
    delta = now_utc_plus_1 - last_birthday
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    uptime = f"{years}y {days}d"
    if now_utc_plus_1.month == BIRTHDAY_MONTH and now_utc_plus_1.day == BIRTHDAY_DAY:
        return f"{BIRTHDAY_EMOJI} {uptime}"
    return uptime


def make_row(label: str, value: str, width: int = 68, dot_shift_left: int = 0) -> str:
    inner_width = width
    left = f"{label} "
    if len(left) + len(value) > inner_width:
        trim_to = max(1, inner_width - len(value) - 1)
        left = f"{label[:trim_to]} "
    dots = "." * max(1, inner_width - len(left) - len(value) - 1 - dot_shift_left)
    return f"{left}{dots} {value}"


def make_title(title: str, width: int = 68) -> str:
    return f" {title} ".center(width, "-")


def draw_cake_icon(draw: ImageDraw.ImageDraw, x: float, y: float, size: int) -> float:
    plate = (212, 220, 228)
    cake = (250, 199, 214)
    icing = (255, 241, 246)
    candle = (95, 223, 160)
    flame = (255, 196, 74)

    icon_w = max(12, int(size * 0.95))
    icon_h = max(12, int(size * 0.95))
    base_y = y + int(size * 0.8)

    draw.rectangle((x + 1, base_y, x + icon_w - 1, base_y + 2), fill=plate)
    draw.rectangle((x + 2, base_y - 7, x + icon_w - 2, base_y), fill=cake)
    draw.rectangle((x + 2, base_y - 10, x + icon_w - 2, base_y - 7), fill=icing)
    candle_x = x + icon_w // 2
    draw.rectangle((candle_x, base_y - 15, candle_x + 1, base_y - 10), fill=candle)
    draw.polygon(
        [(candle_x + 1, base_y - 19), (candle_x - 1, base_y - 16), (candle_x + 3, base_y - 16)],
        fill=flame,
    )
    return float(icon_w + 3)


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
    emoji_font = load_emoji_font(FONT_SIZE)
    probe = Image.new("RGB", (10, 10), COLOR_BG)
    probe_draw = ImageDraw.Draw(probe)
    char_box = probe_draw.textbbox((0, 0), "M", font=font)
    line_box = probe_draw.textbbox((0, 0), "Mg", font=font)
    char_width = char_box[2] - char_box[0]
    line_height = (line_box[3] - line_box[1]) + 6

    uptime_value = format_uptime_since_birthday()
    uptime_dot_shift = 2 if uptime_value.startswith(BIRTHDAY_EMOJI) else 0

    lines: list[tuple[str, tuple[int, int, int], str | None, tuple[int, int, int] | None]] = [
        (make_title("ABOUT ME", ROW_WIDTH), COLOR_TEAL, None, None),
        (make_row("Name", stats["display_name"], ROW_WIDTH), COLOR_WHITE, None, None),
        (make_row("Uptime", uptime_value, ROW_WIDTH, dot_shift_left=uptime_dot_shift), COLOR_WHITE, None, None),
        ("", COLOR_WHITE, None, None),
        (make_title("GITHUB INFO", ROW_WIDTH), COLOR_GREEN, None, None),
        (make_row("Commits", format_number(stats["total_commits_all_time"]), ROW_WIDTH), COLOR_WHITE, None, None),
        (make_row("Public repos", format_number(stats["repos"]), ROW_WIDTH), COLOR_WHITE, None, None),
        # Only keep the colored lines for lines added/removed
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
        (make_row("Active days (this year)", f"{stats['active_days']}", ROW_WIDTH), COLOR_WHITE, None, None),
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
    image = Image.new("RGBA", (image_width, image_height), COLOR_BG + (255,))
    draw = ImageDraw.Draw(image)

    y = PADDING_Y
    for text, color, highlight_text, highlight_color in lines:
        if BIRTHDAY_EMOJI in text:
            prefix, suffix = text.split(BIRTHDAY_EMOJI, 1)
            draw.text((PADDING_X, y), prefix, font=font, fill=color)
            prefix_width = draw.textlength(prefix, font=font)
            cake_x = PADDING_X + prefix_width
            emoji_width = 0.0
            emoji_rendered = False
            if emoji_font is not None:
                try:
                    draw.text((cake_x, y), BIRTHDAY_EMOJI, font=emoji_font, embedded_color=True)
                    emoji_width = draw.textlength(BIRTHDAY_EMOJI, font=emoji_font)
                    emoji_rendered = True
                except Exception:
                    emoji_rendered = False
            if not emoji_rendered:
                emoji_width = draw_cake_icon(draw, cake_x, y, FONT_SIZE)
            draw.text((cake_x + emoji_width, y), suffix, font=font, fill=color)
        else:
            draw.text((PADDING_X, y), text, font=font, fill=color)
        if highlight_text and highlight_color:
            highlight_index = text.rfind(highlight_text)
            if highlight_index >= 0:
                draw.text((PADDING_X + (highlight_index * char_width), y), highlight_text, font=font, fill=highlight_color)
        y += line_height

    image.save(IMAGE_PATH)


def update_readme(stats: dict, cached: bool) -> None:
    cache_tag = "yes" if cached else "no"
    rendered_utc_plus_1 = datetime.now(timezone.utc) + timedelta(hours=1)
    readme_content = (
        f"![GitHub summary]({IMAGE_PATH.name})\n\n"
        f"_Last updated: {format_datetime(rendered_utc_plus_1.isoformat())} UTC+1 - cached: {cache_tag}_\n"
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
