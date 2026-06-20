#!/usr/bin/env python3
"""Fetch LinkedIn engagement stats, award reinforcement scores, and prune losers.

Flow:
  1. Fetch views/likes/comments from LinkedIn shareStatistics API
  2. Award reinforcement += 1 for any post where likes > 1
  3. --prune: delete posts older than GRACE_HOURS that still have likes <= 1,
     mark status="pruned" in post_log.json so the pipeline avoids their patterns

Usage:
  python prompt_lab/fetch_views.py          # fetch + score + leaderboard
  python prompt_lab/fetch_views.py --all    # re-fetch all posts (refresh counts)
  python prompt_lab/fetch_views.py --prune  # fetch + score + delete losers from LinkedIn
"""
import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import requests

POST_LOG = Path(__file__).parent / "results" / "post_log.json"
STATS_URL  = "https://api.linkedin.com/v2/shareStatistics"
DELETE_URL = "https://api.linkedin.com/v2/ugcPosts/{encoded_urn}"

LIKE_THRESHOLD    = 1   # likes must be > this
QUALITY_THRESHOLD = 65  # final_score must be >= this — both conditions required for reinforcement=1
GRACE_HOURS       = 48  # hours after publishing before a post is eligible for pruning


def _auth_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def fetch_stats(access_token: str, person_urn: str) -> dict[str, dict]:
    """Return {post_urn: {views, clicks, likes, comments}} for all recent posts."""
    resp = requests.get(
        STATS_URL,
        headers=_auth_headers(access_token),
        params={"q": "owners", "owners": person_urn, "sharesPerOwner": 100},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LinkedIn stats error {resp.status_code}: {resp.text}")

    result = {}
    for el in resp.json().get("elements", []):
        urn = el.get("share", "")
        s   = el.get("totalShareStatistics", {})
        result[urn] = {
            "views":    s.get("impressionCount", 0),
            "clicks":   s.get("clickCount", 0),
            "likes":    s.get("likeCount", 0),
            "comments": s.get("commentCount", 0),
        }
    return result


def delete_post(access_token: str, post_urn: str) -> bool:
    """Delete a LinkedIn post by URN. Returns True on success (HTTP 204)."""
    encoded = urllib.parse.quote(post_urn, safe="")
    url = DELETE_URL.format(encoded_urn=encoded)
    resp = requests.delete(url, headers=_auth_headers(access_token), timeout=10)
    return resp.status_code == 204


def award_reinforcement(posts: list[dict]) -> int:
    """Award reinforcement=1 only when BOTH conditions hold:
      - likes > LIKE_THRESHOLD       (real engagement)
      - final_score >= QUALITY_THRESHOLD  (technically correct)

    Posts with high likes but low quality are flagged as engagement_bait — they get
    noted in the reinforcement context but do NOT earn reward or become style templates.
    Returns count of posts whose reinforcement value changed.
    """
    changed = 0
    for post in posts:
        if post.get("status") != "live":
            continue
        likes   = post.get("likes") or 0
        quality = post.get("final_score") or 0
        new_r   = 1 if (likes > LIKE_THRESHOLD and quality >= QUALITY_THRESHOLD) else 0
        if post.get("reinforcement", 0) != new_r:
            post["reinforcement"] = new_r
            changed += 1
    return changed


def prune_candidates(posts: list[dict]) -> list[dict]:
    """Return live posts old enough and under-performing enough to prune."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=GRACE_HOURS)
    out = []
    for post in posts:
        if post.get("status") != "live":
            continue
        if post.get("likes") is None:
            continue
        try:
            published = datetime.fromisoformat(post["published_at"])
        except (KeyError, ValueError):
            continue
        if published < cutoff and (post.get("likes") or 0) <= LIKE_THRESHOLD:
            out.append(post)
    return out


def show_leaderboard(posts: list[dict]):
    live   = [p for p in posts if p.get("status") == "live" and p.get("likes") is not None]
    pruned = [p for p in posts if p.get("status") == "pruned"]

    winners = [p for p in live if p.get("reinforcement") == 1]
    bait    = [p for p in live if (p.get("likes") or 0) > LIKE_THRESHOLD
               and (p.get("final_score") or 0) < QUALITY_THRESHOLD]
    total_reward = sum(p.get("reinforcement", 0) for p in posts)

    print(f"\n{'─'*72}")
    print(f"  REINFORCEMENT LEADERBOARD   total_reward={total_reward}  "
          f"live={len(live)}  pruned={len(pruned)}")
    print(f"{'─'*72}")

    if winners:
        print(f"\n  WINNERS — likes > {LIKE_THRESHOLD} AND quality >= {QUALITY_THRESHOLD}  [feed forward as examples]")
        for p in sorted(winners, key=lambda x: x.get("likes", 0), reverse=True):
            print(f"    R+1  {p.get('likes',0):>3} likes  score={p.get('final_score',0):.0f}")
            print(f"         {p['text'][:85]}{'...' if len(p['text']) > 85 else ''}")

    if bait:
        print(f"\n  ENGAGEMENT BAIT — high likes but quality < {QUALITY_THRESHOLD}  [study hook, not content]")
        for p in sorted(bait, key=lambda x: x.get("likes", 0), reverse=True):
            print(f"    ~~   {p.get('likes',0):>3} likes  score={p.get('final_score',0):.0f}")
            print(f"         {p['text'][:85]}{'...' if len(p['text']) > 85 else ''}")

    if pruned:
        print(f"\n  PRUNED — deleted for zero engagement  [avoid these patterns]")
        for p in pruned[-3:]:
            print(f"    ✗    {p['text'][:85]}{'...' if len(p['text']) > 85 else ''}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all",   action="store_true", help="Re-fetch all posts, not just pending ones")
    parser.add_argument("--prune", action="store_true",
                        help=f"Delete live posts older than {GRACE_HOURS}h with likes <= {LIKE_THRESHOLD}")
    args = parser.parse_args()

    if not POST_LOG.exists():
        print("No post_log.json found. Publish a post first: python test_v3.py --publish")
        sys.exit(0)

    posts = json.loads(POST_LOG.read_text()).get("posts", [])

    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    person_urn   = os.environ.get("LINKEDIN_PERSON_URN")
    if not access_token or not person_urn:
        print("Error: LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set in .env")
        sys.exit(1)

    # --- Step 1: fetch stats ---
    if args.all:
        to_fetch = [p for p in posts if p.get("post_urn") and p.get("status") == "live"]
    else:
        to_fetch = [p for p in posts if p.get("views") is None
                    and p.get("post_urn") and p.get("status") == "live"]

    if to_fetch:
        print(f"Fetching stats for {len(to_fetch)} post(s)...")
        stats = fetch_stats(access_token, person_urn)
        now = datetime.now(timezone.utc).isoformat()
        for post in posts:
            urn = post.get("post_urn", "")
            if urn in stats:
                post.update({**stats[urn], "views_fetched_at": now})
        print(f"  Stats updated for {sum(1 for p in posts if p.get('post_urn','') in stats)} post(s).")
    else:
        print("No new posts to fetch stats for.")

    # --- Step 2: award reinforcement ---
    changed = award_reinforcement(posts)
    if changed:
        rewards = sum(1 for p in posts if p.get("reinforcement") == 1)
        print(f"  Reinforcement updated: {rewards} post(s) earned R+1 (likes > {LIKE_THRESHOLD}).")

    # --- Step 3: prune losers ---
    if args.prune:
        candidates = prune_candidates(posts)
        if not candidates:
            print(f"  No posts eligible for pruning "
                  f"(must be >{GRACE_HOURS}h old with likes <= {LIKE_THRESHOLD}).")
        else:
            print(f"\n  Pruning {len(candidates)} under-performing post(s)...")
            now = datetime.now(timezone.utc).isoformat()
            for post in candidates:
                urn = post["post_urn"]
                ok = delete_post(access_token, urn)
                if ok:
                    post["status"] = "pruned"
                    post["deleted_at"] = now
                    print(f"  DELETED {urn}")
                    print(f"    {post['text'][:80]}...")
                else:
                    print(f"  FAILED to delete {urn} — leaving as live")

    POST_LOG.write_text(json.dumps({"posts": posts}, indent=2))
    show_leaderboard(posts)


if __name__ == "__main__":
    main()
