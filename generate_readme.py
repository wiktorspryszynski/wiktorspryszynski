import json
import math
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
LOCAL_UTC_OFFSET_HOURS = 2
NOW_DT = datetime.now(timezone.utc)
CACHE_TTL_SECONDS = 60 * 60  # keep cached payload for one hour
TOKEN = os.environ.get("GH_TOKEN")
BIRTHDAY_EMOJI = "\U0001F382"

if not TOKEN:
    raise SystemExit("GH_TOKEN environment variable must be set before running this script.")

# Display row definitions are kept at the top so labels/keys are easy to tweak.
ABOUT_ME_STAT_ROWS = [
    ("Name", "display_name"),
]
ABOUT_ME_STATIC_ROWS = [
    ("Favorite show", "Naruto"),
    ("Current OS", "Windows 11, EndeavourOS"),
]
GITHUB_COUNT_ROWS = [
    ("Commits", "total_commits_all_time"),
    ("Public repos", "repos"),
]

MY_STACK = [
    ("Python", "icons/python-icon.png"),
    ("JavaScript", "icons/javascript-icon.png"),
    ("TypeScript", "icons/typescript-icon.png"),
    ("React", "icons/react-icon.png"),
    ("SQL", "icons/sql-icon.png"),
    ("PHP", "icons/PHP-icon.png"),
]
STACK_SENTINEL = "__MY_STACK__"

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


def cake_icon_width(size: int) -> float:
    icon_w = max(12, int(size * 0.95))
    return float(icon_w + 3)


def render_image(stats: dict, cached: bool) -> None:
    # 3 customizable terminal accent colors (white is separate base text color).
    COLOR_BG = (8, 16, 20)
    COLOR_WHITE = (232, 241, 247)
    COLOR_TEAL = (45, 212, 191)
    COLOR_GREEN = (134, 239, 172)
    COLOR_RED = (248, 113, 113)
    COLOR_PURPLE = (167, 139, 250)
    LANGUAGE_COLORS = [
        (45, 212, 191),
        (96, 165, 250),
        (251, 191, 36),
        (248, 113, 113),
        (167, 139, 250),
    ]

    FONT_SIZE = 16
    ICON_SIZE = 13
    ROW_WIDTH = 68
    TARGET_IMAGE_WIDTH = 950
    PADDING_X = 26
    PADDING_Y = 22

    font = load_font(FONT_SIZE)
    emoji_font = load_emoji_font(FONT_SIZE)
    probe = Image.new("RGB", (10, 10), COLOR_BG)
    probe_draw = ImageDraw.Draw(probe)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 6

    uptime_value = format_uptime_since_birthday()
    uptime_dot_shift = 2 if uptime_value.startswith(BIRTHDAY_EMOJI) else 0

    def make_line(
        text: str,
        color: tuple[int, int, int] = COLOR_WHITE,
        highlight_text: str | None = None,
        highlight_color: tuple[int, int, int] | None = None,
    ) -> tuple[str, tuple[int, int, int], str | None, tuple[int, int, int] | None]:
        return text, color, highlight_text, highlight_color

    lines: list[tuple[str, tuple[int, int, int], str | None, tuple[int, int, int] | None]] = []

    def add_title(title: str, color: tuple[int, int, int]) -> None:
        if lines:
            lines.append(make_line(""))
        lines.append(make_line(make_title(title, ROW_WIDTH), color))

    add_title("ABOUT ME", COLOR_TEAL)
    lines.extend(make_line(make_row(label, str(stats[stat_key]), ROW_WIDTH)) for label, stat_key in ABOUT_ME_STAT_ROWS)
    lines.extend(make_line(make_row(label, value, ROW_WIDTH)) for label, value in ABOUT_ME_STATIC_ROWS)
    lines.append(make_line(make_row("Uptime", uptime_value, ROW_WIDTH, dot_shift_left=uptime_dot_shift)))
    add_title("GITHUB INFO", COLOR_GREEN)
    lines.extend(make_line(make_row(label, format_number(stats[stat_key]), ROW_WIDTH)) for label, stat_key in GITHUB_COUNT_ROWS)
    # Only keep the colored lines for lines added/removed
    lines.append(
        make_line(
            make_row("Lines added", f"++ {format_number(stats['lines_added'])}", ROW_WIDTH),
            highlight_text=f"++ {format_number(stats['lines_added'])}",
            highlight_color=COLOR_GREEN,
        )
    )
    lines.append(
        make_line(
            make_row("Lines removed", f"-- {format_number(stats['lines_removed'])}", ROW_WIDTH),
            highlight_text=f"-- {format_number(stats['lines_removed'])}",
            highlight_color=COLOR_RED,
        )
    )
    lines.append(make_line(make_row("Net lines", f"{stats['net_lines']:+,}", ROW_WIDTH)))
    lines.append(make_line(make_row("Active days (this year)", f"{stats['active_days']}", ROW_WIDTH)))
    add_title("MY STACK", COLOR_PURPLE)
    lines.append((STACK_SENTINEL, COLOR_WHITE, None, None))
    add_title("TOP LANGUAGES", COLOR_RED)

    # The row width in characters, so estimate pixel width for the rows
    # Use a probe to measure the max row width in pixels
    max_row_pixel_width = 0.0
    for text, _, _, _ in lines:
        if BIRTHDAY_EMOJI in text:
            prefix, suffix = text.split(BIRTHDAY_EMOJI, 1)
            emoji_width = (
                probe_draw.textlength(BIRTHDAY_EMOJI, font=emoji_font)
                if emoji_font is not None
                else cake_icon_width(FONT_SIZE)
            )
            line_width = (
                probe_draw.textlength(prefix, font=font)
                + emoji_width
                + probe_draw.textlength(suffix, font=font)
            )
        elif text == STACK_SENTINEL:
            icon_size = ICON_SIZE
            line_width = probe_draw.textlength("[ ", font=font)
            for i, (name, _) in enumerate(MY_STACK):
                sep = ", " if i < len(MY_STACK) - 1 else ""
                line_width += icon_size + 4 + probe_draw.textlength(name + sep, font=font)
            line_width += probe_draw.textlength(" ]", font=font)
        else:
            line_width = probe_draw.textlength(text, font=font)
        max_row_pixel_width = max(max_row_pixel_width, line_width)

    # Keep the generated image at least this wide for README presentation.
    min_content_width = int(math.ceil((PADDING_X * 2) + max_row_pixel_width)) + 4
    image_width = max(TARGET_IMAGE_WIDTH, min_content_width)
    content_x = int((image_width - max_row_pixel_width) // 2)

    # The chart and legend must fit within the same width as the rows
    chart_width = max_row_pixel_width
    bar_height = 20
    chart_top_gap = 8
    legend_items = stats["languages"] if stats["languages"] else [{"name": "No data", "percent": 0.0}]
    legend_row_height = line_height - 2
    chart_block_height = chart_top_gap + bar_height + 10 + (legend_row_height * len(legend_items))

    image_height = int(math.ceil((PADDING_Y * 2) + (line_height * len(lines)) + chart_block_height)) + 4
    image = Image.new("RGBA", (image_width, image_height), COLOR_BG + (255,))
    draw = ImageDraw.Draw(image)

    y = PADDING_Y
    for text, color, highlight_text, highlight_color in lines:
        if BIRTHDAY_EMOJI in text:
            prefix, suffix = text.split(BIRTHDAY_EMOJI, 1)
            draw.text((content_x, y), prefix, font=font, fill=color)
            prefix_width = draw.textlength(prefix, font=font)
            cake_x = content_x + prefix_width
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
        elif text == STACK_SENTINEL:
            icon_size = ICON_SIZE
            icon_top = y + (line_height - icon_size) // 2 - 3
            cursor = float(content_x)
            draw.text((cursor, y), "[ ", font=font, fill=COLOR_WHITE)
            cursor += draw.textlength("[ ", font=font)
            for i, (name, icon_path) in enumerate(MY_STACK):
                try:
                    icon = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    image.paste(icon, (int(cursor), icon_top), icon)
                except Exception:
                    pass
                cursor += icon_size + 4
                sep = ", " if i < len(MY_STACK) - 1 else ""
                draw.text((cursor, y), name + sep, font=font, fill=COLOR_WHITE)
                cursor += draw.textlength(name + sep, font=font)
            draw.text((cursor, y), " ]", font=font, fill=COLOR_WHITE)
        else:
            draw.text((content_x, y), text, font=font, fill=color)
        if highlight_text and highlight_color:
            highlight_index = text.rfind(highlight_text)
            if highlight_index >= 0:
                prefix = text[:highlight_index]
                highlight_x = content_x + draw.textlength(prefix, font=font)
                draw.text((highlight_x, y), highlight_text, font=font, fill=highlight_color)
        y += line_height

    # Draw the chart and legend within the same width as the rows
    bar_x = content_x
    bar_y = y + chart_top_gap
    bar_w = int(chart_width)
    bar_h = bar_height
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=8, outline=(60, 74, 88), width=1)

    if stats["languages"]:
        normalized = []
        for language in stats["languages"]:
            normalized.append(
                {
                    "name": language["name"],
                    "percent": max(0.0, float(language["percent"])),
                }
            )

        total_percent = sum(item["percent"] for item in normalized)
        if total_percent > 0:
            scaled = [{"name": item["name"], "percent": item["percent"] * 100 / total_percent} for item in normalized]
        else:
            scaled = normalized

        cursor_x = bar_x
        for idx, language in enumerate(scaled):
            segment_w = int(round((language["percent"] / 100) * bar_w))
            if idx == len(scaled) - 1:
                segment_w = (bar_x + bar_w) - cursor_x
            color = LANGUAGE_COLORS[idx % len(LANGUAGE_COLORS)]
            if segment_w > 0:
                draw.rectangle((cursor_x, bar_y, cursor_x + segment_w, bar_y + bar_h), fill=color)
                cursor_x += segment_w

        legend_y = bar_y + bar_h + 10
        for idx, language in enumerate(stats["languages"]):
            color = LANGUAGE_COLORS[idx % len(LANGUAGE_COLORS)]
            swatch = 10
            row_y = legend_y + (idx * legend_row_height)
            draw.rectangle((bar_x, row_y + 4, bar_x + swatch, row_y + 4 + swatch), fill=color)
            legend_text = f"{language['name']}  {language['percent']:.1f}%"
            draw.text((bar_x + 16, row_y), legend_text, font=font, fill=COLOR_WHITE)
    else:
        draw.text((bar_x, bar_y + 2), "No language data available", font=font, fill=COLOR_WHITE)

    image.save(IMAGE_PATH)


def update_readme(stats: dict, cached: bool) -> None:
    cache_tag = "yes" if cached else "no"
    rendered_local = datetime.now(timezone.utc) + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    utc_label = f"UTC{LOCAL_UTC_OFFSET_HOURS:+d}"
    readme_content = (
        f"![GitHub summary]({IMAGE_PATH.name})\n\n"
        f"Last updated: {format_datetime(rendered_local.isoformat())} {utc_label} - cached: {cache_tag}\n"
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
