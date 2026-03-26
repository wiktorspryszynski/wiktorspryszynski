import requests
from datetime import datetime, UTC

USERNAME = "wiktorspryszynski"


def get_github_data():
    url = f"https://api.github.com/users/{USERNAME}"
    response = requests.get(url)
    data = response.json()

    return {
        "repos": data.get("public_repos", 0),
        "followers": data.get("followers", 0),
    }


def generate_ascii(data):
    return f"""
        ╔══════════════════════════════╗
        ║        GITHUB STATS          ║
        ╠══════════════════════════════╣
        ║ Repositories : {data['repos']:>10} ║
        ║ Followers    : {data['followers']:>10} ║
        ║ Updated      : {datetime.now(UTC).strftime("%Y-%m-%d")} ║
        ╚══════════════════════════════╝
        """


def main():
    data = get_github_data()
    ascii_block = generate_ascii(data)

    readme_content = f"""
    # Hi 👋

    ## 📊 Stats

    ~~~
    {ascii_block}
    ~~~

    _Last update: {datetime.now(UTC)}_
    """

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)


if __name__ == "__main__":
    main()