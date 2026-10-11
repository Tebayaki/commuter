import requests
import re

def push_message(title: str, content: str, serverchan_key: str) -> None:
    """Push a message through Server酱."""
    match = re.match(r"sctp(\d+)t", serverchan_key)
    uid = match.group(1) if match else serverchan_key[:3]
    api_url = f"https://{uid}.push.ft07.com/send/{serverchan_key}.send"
    response = requests.post(
        api_url,
        json={"title": title, "desp": content},
        timeout=10,
    )
    response.raise_for_status()
