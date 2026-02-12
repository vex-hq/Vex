import os
import sys
import json
import time
import random
import argparse
import httpx
from datetime import datetime, timedelta

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, IntPrompt
from rich.markdown import Markdown
from rich import box

from agentguard import AgentGuard, AgentGuardBlockError, GuardConfig, GuardResult

load_dotenv()

USE_API = True            # Set to False via --no-api flag
SYNC_MODE = False         # Set to True via --sync flag
CORRECTION_MODE = False   # Set to True via --correction flag
SCENARIO = "default"      # Set via --scenario flag

AGENT_ID = "hive-sms-agent"
AGENTGUARD_API_URL = os.getenv("AGENTGUARD_API_URL", "http://localhost:8000")

guard = None  # Initialized lazily via build_guard() after CLI args are parsed


def build_guard():
    """Create the AgentGuard instance based on CLI flags."""
    global guard
    timeout_s = float(os.getenv("AGENTGUARD_TIMEOUT_S", "30.0"))
    guard = AgentGuard(
        api_key=os.getenv("AGENTGUARD_API_KEY", "ag_demo_key"),
        config=GuardConfig(
            api_url=AGENTGUARD_API_URL,
            mode="sync" if SYNC_MODE else "async",
            correction="cascade" if CORRECTION_MODE else "none",
            transparency="transparent" if CORRECTION_MODE else "opaque",
            flush_interval_s=1.0,
            flush_batch_size=10,
            timeout_s=timeout_s,
        ),
    )
    # The SDK v0.2.0 hardcodes correction_timeout_s=12.0 which is too low
    # for LLM-based correction cascades. Override it to match the configured
    # timeout when correction mode is enabled.
    if CORRECTION_MODE and guard._sync_transport is not None:
        guard._sync_transport.correction_timeout_s = max(timeout_s * 2, 60.0)
        # Recreate the correction client with the new timeout if it was
        # already lazily created (it shouldn't be at init time, but be safe)
        if guard._sync_transport._correction_client is not None:
            guard._sync_transport._correction_client.close()
            guard._sync_transport._correction_client = None

console = Console()

# ── Sample Data ─────────────────────────────────────────────

VENUE = {
    "name": "Miller Theater",
    "capacity": 500,
    "brand_voice": "casual",
    "genres": ["jazz", "rock", "indie"],
    "words_to_avoid": ["cheap", "discount", "last chance"],
    "preferred_send_days": ["Tuesday", "Thursday"],
    "preferred_send_hours": "5pm-7pm",
    "quiet_hours_start": "21:00",
    "quiet_hours_end": "09:00",
    "max_monthly_messages": 4,
}

SEGMENTS = [
    {"name": "Jazz Enthusiasts", "count": 342, "description": "Attended 2+ jazz shows in last 6 months"},
    {"name": "Rock & Indie Fans", "count": 518, "description": "Engaged with rock/indie show emails, high open rates"},
    {"name": "VIP Repeat Buyers", "count": 89, "description": "Purchased tickets to 5+ shows this year"},
    {"name": "Lapsed Attendees", "count": 276, "description": "Attended a show 3-6 months ago, no recent activity"},
    {"name": "All Subscribers", "count": 1247, "description": "Full subscriber list"},
]

today = datetime.now()

SHOWS = [
    {
        "name": "Jazz Night Live ft. Sarah Chen Quartet",
        "date": (today + timedelta(days=8)).strftime("%b %d"),
        "date_full": (today + timedelta(days=8)).strftime("%A, %B %d"),
        "genre": "jazz",
        "capacity": 500,
        "tickets_sold": 290,
        "tickets_pct": 58,
    },
    {
        "name": "Indie Showcase: The Wanderers + Pale Moon",
        "date": (today + timedelta(days=15)).strftime("%b %d"),
        "date_full": (today + timedelta(days=15)).strftime("%A, %B %d"),
        "genre": "indie",
        "capacity": 500,
        "tickets_sold": 425,
        "tickets_pct": 85,
    },
    {
        "name": "Rock Marathon: 4 Bands, 1 Night",
        "date": (today + timedelta(days=22)).strftime("%b %d"),
        "date_full": (today + timedelta(days=22)).strftime("%A, %B %d"),
        "genre": "rock",
        "capacity": 500,
        "tickets_sold": 205,
        "tickets_pct": 41,
    },
    {
        "name": "Late Night Jazz Jam Session",
        "date": (today + timedelta(days=30)).strftime("%b %d"),
        "date_full": (today + timedelta(days=30)).strftime("%A, %B %d"),
        "genre": "jazz",
        "capacity": 300,
        "tickets_sold": 210,
        "tickets_pct": 70,
    },
    {
        "name": "Acoustic Indie Fridays",
        "date": (today + timedelta(days=36)).strftime("%b %d"),
        "date_full": (today + timedelta(days=36)).strftime("%A, %B %d"),
        "genre": "indie",
        "capacity": 200,
        "tickets_sold": 160,
        "tickets_pct": 80,
    },
]

PAST_CAMPAIGNS = [
    {"show": "Blues & Brews Night", "segment": "Jazz Enthusiasts", "sent": 310, "delivered": 298, "clicked": 71, "opted_out": 2, "ctr": "23.8%"},
    {"show": "Rock the Block Party", "segment": "Rock & Indie Fans", "sent": 482, "delivered": 470, "clicked": 84, "opted_out": 3, "ctr": "17.9%"},
    {"show": "Valentine Jazz Special", "segment": "VIP Repeat Buyers", "sent": 85, "delivered": 84, "clicked": 29, "opted_out": 0, "ctr": "34.5%"},
]


# ── Scenario Data ───────────────────────────────────────────

SCENARIO_GUARDRAIL = {
    "venue": {
        "name": "The Basement",
        "capacity": 200,
        "brand_voice": "edgy",
        "genres": ["punk", "metal", "hardcore"],
        "words_to_avoid": ["exclusive", "VIP", "free", "elegant", "classy"],
        "preferred_send_days": ["Wednesday", "Friday"],
        "preferred_send_hours": "4pm-7pm",
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "09:00",
        "max_monthly_messages": 4,
    },
    "segments": [
        {"name": "Mosh Pit Regulars", "count": 287, "description": "Attended 3+ punk/metal shows, high energy fans"},
        {"name": "New Discoverers", "count": 156, "description": "Signed up in last 30 days, haven't attended yet"},
        {"name": "All Subscribers", "count": 612, "description": "Full subscriber list"},
    ],
    "shows": lambda today: [
        {
            "name": "Skull Crusher + Dead Voltage",
            "date": (today + timedelta(days=5)).strftime("%b %d"),
            "date_full": (today + timedelta(days=5)).strftime("%A, %B %d"),
            "genre": "metal",
            "capacity": 200,
            "tickets_sold": 68,
            "tickets_pct": 34,
        },
        {
            "name": "Punk Basement Sessions Vol. 12",
            "date": (today + timedelta(days=12)).strftime("%b %d"),
            "date_full": (today + timedelta(days=12)).strftime("%A, %B %d"),
            "genre": "punk",
            "capacity": 200,
            "tickets_sold": 150,
            "tickets_pct": 75,
        },
    ],
    "past_campaigns": [
        {"show": "Thrash Thursday", "segment": "Mosh Pit Regulars", "sent": 265, "delivered": 258, "clicked": 62, "opted_out": 1, "ctr": "24.0%"},
    ],
    "fallback": {
        "segment": {
            "name": "Mosh Pit Regulars",
            "reasoning": "287 hardcore fans who attend regularly. Metal shows convert best with this segment — 24% CTR historically."
        },
        "copy_options": [
            {"id": 1, "text": "Skull Crusher + Dead Voltage this Friday. Exclusive early entry for subscribers. It's gonna be brutal 🤘", "angle": "exclusive access"},
            {"id": 2, "text": "Friday just got heavier. Skull Crusher + Dead Voltage live at The Basement. Don't miss this VIP experience", "angle": "VIP experience"},
            {"id": 3, "text": "The pit is calling. Skull Crusher + Dead Voltage, Friday at The Basement. Tix going fast", "angle": "urgency + energy"},
        ],
        "send_time": {
            "day": "Wednesday",
            "time": "5:00 PM",
            "date": (datetime.now() + timedelta(days=3)).strftime("%A, %B %d"),
            "reasoning": "Wednesday gives 2 days before Friday show. Your metal fans are most active Wed-Fri evenings."
        },
    },
}

SCENARIO_SMALL = {
    "venue": {
        "name": "Rosie's Corner Bar",
        "capacity": 60,
        "brand_voice": "friendly",
        "genres": ["acoustic", "folk", "singer-songwriter"],
        "words_to_avoid": ["wild", "crazy", "insane"],
        "preferred_send_days": ["Thursday"],
        "preferred_send_hours": "12pm-2pm",
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "09:00",
        "max_monthly_messages": 4,
    },
    "segments": [
        {"name": "All Subscribers", "count": 47, "description": "Full subscriber list — too small for meaningful segmentation"},
    ],
    "shows": lambda today: [
        {
            "name": "Open Mic Night ft. Local Artists",
            "date": (today + timedelta(days=6)).strftime("%b %d"),
            "date_full": (today + timedelta(days=6)).strftime("%A, %B %d"),
            "genre": "acoustic",
            "capacity": 60,
            "tickets_sold": 18,
            "tickets_pct": 30,
        },
    ],
    "past_campaigns": [],
    "fallback": {
        "segment": {
            "name": "All Subscribers",
            "reasoning": "With 47 contacts, segmentation isn't meaningful. Sending to all subscribers maximizes reach for this small venue."
        },
        "copy_options": [
            {"id": 1, "text": "Open Mic Night this week at Rosie's! Local artists, great vibes. Come join us", "angle": "warm invitation"},
            {"id": 2, "text": "Your neighborhood spot has live music this week. Open Mic Night at Rosie's Corner Bar", "angle": "local community"},
            {"id": 3, "text": "Live music + good drinks. Open Mic Night at Rosie's. Bring a friend, it's gonna be great", "angle": "social + casual"},
        ],
        "send_time": {
            "day": "Thursday",
            "time": "12:30 PM",
            "date": (datetime.now() + timedelta(days=4)).strftime("%A, %B %d"),
            "reasoning": "Lunch hour on Thursday — small venue audiences check phones during breaks. Only send day in preferences."
        },
    },
}

SCENARIO_SPIKE = {
    "description": "Uses default Miller Theater data but simulates a bad opt-out spike in results",
}

SCENARIO_ONBOARDING = {
    "venue": {
        "name": "The Blue Note Lounge",
        "capacity": 150,
        "brand_voice": "",
        "genres": [],
        "words_to_avoid": [],
        "preferred_send_days": [],
        "preferred_send_hours": "",
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "09:00",
        "max_monthly_messages": 4,
    },
    "segments": [
        {"name": "All Subscribers", "count": 213, "description": "Imported from email list — no behavioral data yet"},
    ],
    "shows": lambda today: [
        {
            "name": "Grand Opening Weekend: Live Jazz & Blues",
            "date": (today + timedelta(days=10)).strftime("%b %d"),
            "date_full": (today + timedelta(days=10)).strftime("%A, %B %d"),
            "genre": "jazz",
            "capacity": 150,
            "tickets_sold": 22,
            "tickets_pct": 15,
        },
        {
            "name": "Saturday Night Soul & R&B",
            "date": (today + timedelta(days=17)).strftime("%b %d"),
            "date_full": (today + timedelta(days=17)).strftime("%A, %B %d"),
            "genre": "soul",
            "capacity": 150,
            "tickets_sold": 0,
            "tickets_pct": 0,
        },
    ],
    "past_campaigns": [],
    "fallback": {
        "segment": {
            "name": "All Subscribers",
            "reasoning": "No behavioral segments available yet. Sending to all 213 imported contacts for the first campaign."
        },
        "copy_options": [
            {"id": 1, "text": "The Blue Note Lounge is OPEN! Grand Opening Weekend with live jazz & blues. Be there", "angle": "excitement + announcement"},
            {"id": 2, "text": "Live jazz & blues at our Grand Opening this weekend. Come see what we're about", "angle": "invitation + curiosity"},
            {"id": 3, "text": "Grand Opening: live jazz, great drinks, new venue. The Blue Note Lounge is here", "angle": "new venue energy"},
        ],
        "send_time": {
            "day": "Thursday",
            "time": "12:00 PM",
            "date": (datetime.now() + timedelta(days=3)).strftime("%A, %B %d"),
            "reasoning": "Industry data shows lunchtime sends get strong open rates for new venue announcements. Using safe defaults until we learn your audience."
        },
    },
}

SCENARIO_OVERLAP = {
    "venue": None,  # Uses default Miller Theater
    "shows": lambda today: [
        {
            "name": "Jazz Night Live ft. Sarah Chen Quartet",
            "date": (today + timedelta(days=5)).strftime("%b %d"),
            "date_full": (today + timedelta(days=5)).strftime("%A, %B %d"),
            "genre": "jazz",
            "capacity": 500,
            "tickets_sold": 225,
            "tickets_pct": 45,
        },
        {
            "name": "Jazz Brunch: Sunday Sessions",
            "date": (today + timedelta(days=7)).strftime("%b %d"),
            "date_full": (today + timedelta(days=7)).strftime("%A, %B %d"),
            "genre": "jazz",
            "capacity": 300,
            "tickets_sold": 120,
            "tickets_pct": 40,
        },
        {
            "name": "Rock Marathon: 4 Bands, 1 Night",
            "date": (today + timedelta(days=14)).strftime("%b %d"),
            "date_full": (today + timedelta(days=14)).strftime("%A, %B %d"),
            "genre": "rock",
            "capacity": 500,
            "tickets_sold": 310,
            "tickets_pct": 62,
        },
    ],
}


def apply_scenario():
    """Replace module-level data based on the active SCENARIO."""
    global VENUE, SEGMENTS, SHOWS, PAST_CAMPAIGNS, FALLBACK_CAMPAIGN

    if SCENARIO == "guardrail":
        s = SCENARIO_GUARDRAIL
        VENUE = s["venue"]
        SEGMENTS = s["segments"]
        SHOWS = s["shows"](datetime.now())
        PAST_CAMPAIGNS = s["past_campaigns"]
        FALLBACK_CAMPAIGN = s["fallback"]

    elif SCENARIO == "small":
        s = SCENARIO_SMALL
        VENUE = s["venue"]
        SEGMENTS = s["segments"]
        SHOWS = s["shows"](datetime.now())
        PAST_CAMPAIGNS = s["past_campaigns"]
        FALLBACK_CAMPAIGN = s["fallback"]

    elif SCENARIO == "overlap":
        s = SCENARIO_OVERLAP
        SHOWS = s["shows"](datetime.now())
        # Keep default venue, segments, past_campaigns

    elif SCENARIO == "onboarding":
        s = SCENARIO_ONBOARDING
        VENUE = s["venue"]
        SEGMENTS = s["segments"]
        SHOWS = s["shows"](datetime.now())
        PAST_CAMPAIGNS = s["past_campaigns"]
        FALLBACK_CAMPAIGN = s["fallback"]

    # "spike" and "default" use the default data as-is


# ── Fallback Campaign (for --no-api or API failure) ─────────

FALLBACK_CAMPAIGN = {
    "segment": {
        "name": "Jazz Enthusiasts",
        "reasoning": "342 jazz fans who attended 2+ similar shows but haven't purchased tickets for this event. Past jazz campaigns hit 23.8% CTR with this segment."
    },
    "copy_options": [
        {"id": 1, "text": "Jazz Night is back at Miller! Sarah Chen Quartet live. Grab your tix before they're gone", "angle": "urgency + artist"},
        {"id": 2, "text": "You loved our last jazz night. Same vibes, new sounds. Sarah Chen Quartet, live at Miller", "angle": "past experience"},
        {"id": 3, "text": "Live jazz. Great night out. Sarah Chen Quartet at Miller Theater. Tix selling fast", "angle": "simple + social"},
    ],
    "send_time": {
        "day": "Tuesday",
        "time": "6:00 PM",
        "date": "next Tuesday",
        "reasoning": "Your jazz fans open 40% more on Tuesday evenings. Past campaigns sent Tue 5-7pm saw highest CTR."
    },
}


# ── LLM Integration ─────────────────────────────────────────

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def call_llm(show: dict, venue: dict, segments: list, past_campaigns: list) -> tuple:
    """Call OpenRouter to generate a complete campaign.

    Returns:
        A tuple of (campaign_dict, usage_dict) where usage_dict contains
        token counts from the API response (or None if unavailable).
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        console.print("[red]ERROR: OPENROUTER_API_KEY not set in .env[/red]")
        sys.exit(1)

    system_prompt = """You are an AI SMS marketing agent for music venues developed by Hive.
You create targeted SMS campaigns that sell tickets.

You must respond with ONLY valid JSON (no markdown, no code fences) in this exact structure:
{
  "segment": {
    "name": "segment name from the provided list",
    "reasoning": "1-2 sentence explanation of why this segment"
  },
  "copy_options": [
    {"id": 1, "text": "SMS copy option 1 (max 140 chars to leave room for opt-out)", "angle": "2-3 word description of the angle"},
    {"id": 2, "text": "SMS copy option 2 (max 140 chars)", "angle": "angle description"},
    {"id": 3, "text": "SMS copy option 3 (max 140 chars)", "angle": "angle description"}
  ],
  "send_time": {
    "day": "day of week",
    "time": "HH:MM AM/PM",
    "date": "full date string",
    "reasoning": "1-2 sentence explanation"
  }
}

Rules:
- Each SMS must be ≤140 characters (to leave room for opt-out text)
- Match the venue's brand voice
- Never use words from the avoid list
- Each copy option should take a different angle/tone
- Send time must be within preferred hours and not during quiet hours
- Reference past campaign performance when choosing segment/timing"""

    user_prompt = f"""Create an SMS campaign for this show:

SHOW: {show['name']}
DATE: {show['date_full']}
GENRE: {show['genre']}
TICKETS SOLD: {show['tickets_pct']}% ({show['tickets_sold']}/{show['capacity']})

VENUE PROFILE:
- Name: {venue['name']}
- Brand voice: {venue['brand_voice']}
- Genres: {', '.join(venue['genres'])}
- Words to avoid: {', '.join(venue['words_to_avoid'])}
- Preferred send days: {', '.join(venue['preferred_send_days'])}
- Preferred send hours: {venue['preferred_send_hours']}
- Quiet hours: {venue['quiet_hours_start']} - {venue['quiet_hours_end']}

AVAILABLE SEGMENTS:
{json.dumps(segments, indent=2)}

PAST CAMPAIGN PERFORMANCE:
{json.dumps(past_campaigns, indent=2)}

Generate the optimal campaign. Pick the best segment, write 3 copy options with different angles, and recommend the best send time."""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hive.co",
        "X-Title": "Hive AI SMS Agent Demo",
    }

    payload = {
        "model": "x-ai/grok-4.1-fast",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    response = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30.0)
    response.raise_for_status()

    # Some models return leading whitespace — parse carefully
    raw_body = response.text.strip()
    body = json.loads(raw_body)
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage")

    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
    if content.endswith("```"):
        content = content.rsplit("```", 1)[0]
    content = content.strip()

    return json.loads(content), usage


# ── Agent Steps ─────────────────────────────────────────────

def thinking_pause(seconds=1.0):
    """Brief pause to simulate agent thinking."""
    time.sleep(seconds)

def step_header(number, title):
    """Print a step header."""
    console.print()
    console.print(f"[bold cyan]▸ Step {number}:[/bold cyan] [bold]{title}[/bold]")
    console.print()

def step_load_venue():
    """Step 1: Load and display venue profile."""
    step_header(1, "Loading venue profile...")
    thinking_pause(0.8)

    genre_str = ", ".join(VENUE["genres"]).title() if VENUE["genres"] else "[dim italic]Not configured[/dim italic]"
    avoid_str = ", ".join(f'"{w}"' for w in VENUE["words_to_avoid"]) if VENUE["words_to_avoid"] else "[dim italic]Not configured[/dim italic]"
    voice_str = VENUE["brand_voice"].title() if VENUE["brand_voice"] else "[dim italic]Not configured[/dim italic]"
    send_days_str = ", ".join(VENUE["preferred_send_days"]) if VENUE["preferred_send_days"] else "[dim italic]Not configured[/dim italic]"

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    table.add_column("Key", style="dim", width=20)
    table.add_column("Value", style="bold")
    table.add_row("Venue", VENUE["name"])
    table.add_row("Brand Voice", voice_str)
    table.add_row("Genres", genre_str)
    table.add_row("Capacity", str(VENUE["capacity"]))
    table.add_row("Total Subscribers", f"{SEGMENTS[-1]['count']:,}")
    table.add_row("Active Segments", str(len(SEGMENTS)))
    table.add_row("Words to Avoid", avoid_str)
    table.add_row("Send Days", send_days_str)

    console.print(Panel(table, title="[bold]Venue Profile[/bold]", border_style="blue"))

    # New venue onboarding advisory
    if SCENARIO == "onboarding":
        thinking_pause(0.3)
        console.print(Panel(
            '[bold yellow]⚠ NEW VENUE — FIRST-TIME SETUP DETECTED[/bold yellow]\n\n'
            'This venue has [bold]no campaign history[/bold] and an [bold]incomplete profile[/bold].\n\n'
            '[bold]Cold start strategy:[/bold]\n'
            '  • Using [bold]industry benchmarks[/bold] instead of historical data\n'
            '    (Music venue SMS avg: 18% CTR, <1% opt-out)\n'
            '  • Skipping segmentation — sending to [bold]all subscribers[/bold]\n'
            '  • Full human-in-the-loop — [bold]every decision needs approval[/bold]\n'
            '  • Conservative frequency: max 2 campaigns/month until data builds\n\n'
            '[bold]Progressive autonomy roadmap:[/bold]\n'
            '  [dim]Campaigns 1-3:[/dim]  Full approval on everything\n'
            '  [dim]Campaigns 4-10:[/dim] Auto-select segments & timing, copy needs approval\n'
            '  [dim]Campaigns 10+:[/dim]  Auto-send routine campaigns, high-stakes still approved\n\n'
            '[dim italic]Tip: Use --chat mode for a guided onboarding conversation.[/dim italic]',
            title="[bold yellow]🤖 Onboarding Advisory[/bold yellow]",
            border_style="yellow",
        ))

    # Small venue warning
    total_subs = SEGMENTS[-1]["count"] if SEGMENTS else 0
    if total_subs < 100 and SCENARIO != "onboarding":
        thinking_pause(0.3)
        console.print(Panel(
            f'[bold yellow]⚠ Small audience detected ({total_subs} contacts)[/bold yellow]\n\n'
            f'With fewer than 100 contacts, the AI will:\n'
            f'  • Skip segmentation — send to all subscribers\n'
            f'  • Use industry best practices instead of historical data\n'
            f'  • Apply conservative frequency (max 2/month until audience grows)',
            title="[bold yellow]🤖 Agent Advisory[/bold yellow]",
            border_style="yellow",
        ))

    thinking_pause(0.5)


def step_scan_shows():
    """Step 2: Scan show calendar and display opportunities."""
    step_header(2, "Scanning show calendar...")
    thinking_pause(1.0)

    table = Table(box=box.ROUNDED)
    table.add_column("Show", style="bold", width=40)
    table.add_column("Date", width=10)
    table.add_column("Sold", justify="right", width=8)
    table.add_column("Urgency", justify="center", width=10)

    for show in SHOWS:
        pct = show["tickets_pct"]
        if pct < 50:
            urgency = "[bold red]🔴 HIGH[/bold red]"
            sold_style = "red"
        elif pct < 75:
            urgency = "[bold yellow]🟡 MEDIUM[/bold yellow]"
            sold_style = "yellow"
        else:
            urgency = "[bold green]🟢 LOW[/bold green]"
            sold_style = "green"

        table.add_row(
            show["name"],
            show["date"],
            f"[{sold_style}]{pct}%[/{sold_style}]",
            urgency,
        )

    console.print(table)
    thinking_pause(0.5)


def step_select_show() -> dict:
    """Step 3: Agent selects the highest-priority show."""
    step_header(3, "Agent analyzing opportunities...")
    thinking_pause(1.5)

    # Score shows: lower ticket % = higher priority, skip shows selling well
    scored = []
    for show in SHOWS:
        unsold_pct = 100 - show["tickets_pct"]
        score = unsold_pct
        if show["tickets_pct"] >= 80:
            score = 0  # Skip shows that are selling well
        scored.append((score, show))

    scored.sort(key=lambda x: -x[0])
    selected = scored[0][1]

    # Overlap detection: check if multiple high-priority shows share a genre
    high_priority = [(s, show) for s, show in scored if s > 20]
    genre_groups = {}
    for s, show in high_priority:
        genre_groups.setdefault(show["genre"], []).append(show)

    overlap_detected = False
    for genre, shows_in_genre in genre_groups.items():
        if len(shows_in_genre) > 1:
            overlap_detected = True
            console.print(Panel(
                f'[bold yellow]⚠ OVERLAP DETECTED[/bold yellow]\n\n'
                f'[bold]{len(shows_in_genre)} {genre} shows[/bold] need campaigns this week:\n' +
                "\n".join(f'  • {s["name"]} ({s["date"]}, {100-s["tickets_pct"]}% unsold)' for s in shows_in_genre) +
                f'\n\n[bold]Decision:[/bold] Sending for both would oversaturate {genre} fans.\n'
                f'Prioritizing [bold]{shows_in_genre[0]["name"]}[/bold] (higher unsold %).\n'
                f'Second show will be queued — sends only if frequency cap allows.',
                title="[bold yellow]🤖 Audience Overlap Alert[/bold yellow]",
                border_style="yellow",
            ))
            thinking_pause(1.0)

    unsold = 100 - selected["tickets_pct"]
    reasoning = (
        f'[bold]"{selected["name"]}"[/bold] has [bold red]{unsold}% unsold tickets[/bold red] '
        f'and is [bold]{selected["date"]}[/bold] — only days away.\n\n'
        f'This is the [bold]highest priority[/bold] opportunity. Recommending a campaign.'
    )
    if overlap_detected:
        reasoning += f'\n[dim]Other overlapping shows queued for later.[/dim]'

    console.print(Panel(
        reasoning,
        title="[bold cyan]🤖 Agent Reasoning[/bold cyan]",
        border_style="cyan",
    ))
    thinking_pause(0.5)
    return selected


def step_generate_campaign(show: dict) -> tuple:
    """Step 4: Call LLM to generate the campaign, then run through AgentGuard verification.

    Returns:
        A tuple of (campaign_dict, usage_dict, guard_result) where:
        - campaign_dict may be None if blocked
        - usage_dict may be None if offline or unavailable
        - guard_result is a GuardResult (or None in async/offline mode)
    """
    step_header(4, "Generating campaign with AI...")

    if not USE_API:
        console.print("[yellow]⚠ Running in offline mode (--no-api)[/yellow]")
        thinking_pause(1.0)
        console.print("[green]✓[/green] Campaign generated (using fallback data)\n")
        return FALLBACK_CAMPAIGN, None, None

    # Closure to capture usage alongside the campaign output
    call_state = {}

    def generate():
        campaign, usage = call_llm(show, VENUE, SEGMENTS, PAST_CAMPAIGNS)
        call_state["usage"] = usage
        return campaign

    try:
        with console.status("[bold cyan]Calling AI model...[/bold cyan]", spinner="dots"):
            result = guard.run(
                agent_id=AGENT_ID,
                fn=generate,
                task=f"Generate SMS campaign for {show['name']}",
                input_data={"show": show["name"], "venue": VENUE["name"]},
            )
        campaign = result.output
        usage = call_state.get("usage")
        console.print("[green]✓[/green] Campaign generated\n")
        thinking_pause(0.3)
        return campaign, usage, result

    except AgentGuardBlockError as e:
        console.print("[red]✗[/red] Campaign generated but [bold red]blocked by verification[/bold red]\n")
        return None, call_state.get("usage"), e.result

    except Exception as e:
        console.print(f"[yellow]⚠ API call failed: {e}[/yellow]")
        console.print("[yellow]  Falling back to pre-built campaign data...[/yellow]")
        thinking_pause(0.5)
        console.print("[green]✓[/green] Campaign generated (fallback)\n")
        return FALLBACK_CAMPAIGN, None, None


def _confidence_color(score):
    """Return a Rich color tag based on confidence score."""
    if score >= 0.8:
        return "green"
    elif score >= 0.5:
        return "yellow"
    return "red"


def _action_badge(action):
    """Return a styled Rich badge for the verification action."""
    if action == "pass":
        return "[bold green]PASS[/bold green]"
    elif action == "flag":
        return "[bold yellow]FLAG[/bold yellow]"
    return "[bold red]BLOCK[/bold red]"


def step_verify_result(result):
    """Step 4b: Display AgentGuard verification results."""
    step_header("4b", "AgentGuard Verification")

    if result is None:
        # Async mode or offline — no inline verification
        console.print("[dim]Verification mode: async (results available in dashboard)[/dim]")
        return

    if result.confidence is None:
        # Backend unreachable or async — pass-through
        console.print(Panel(
            "[dim italic]Verification unavailable — pass-through mode[/dim italic]\n\n"
            "[dim]The verification backend did not return a confidence score.\n"
            "The output was passed through without blocking.[/dim]",
            title="[bold dim]AgentGuard Verification[/bold dim]",
            border_style="dim",
        ))
        return

    color = _confidence_color(result.confidence)
    badge = _action_badge(result.action)

    # Main confidence + action line
    lines = [
        f"[bold]Confidence:[/bold] [{color}]{result.confidence:.0%}[/{color}]  |  "
        f"[bold]Action:[/bold] {badge}"
    ]

    # Individual check scores from verification dict
    if result.verification:
        lines.append("")
        lines.append("[bold]Checks:[/bold]")
        for check_name, check_data in result.verification.items():
            if isinstance(check_data, dict):
                score = check_data.get("score")
                if score is not None:
                    c = _confidence_color(score)
                    lines.append(f"  [{c}]●[/{c}] {check_name}: [{c}]{score:.0%}[/{c}]")

    # Correction info
    if result.corrected:
        lines.append("")
        lines.append("[bold cyan]Output was auto-corrected by cascade.[/bold cyan]")
        if result.original_output:
            original_str = json.dumps(result.original_output, indent=2) if isinstance(result.original_output, dict) else str(result.original_output)
            if len(original_str) > 200:
                original_str = original_str[:200] + "..."
            lines.append(f"[dim]Original output (truncated):[/dim]\n[dim italic]{original_str}[/dim italic]")

    if result.corrections:
        lines.append("")
        lines.append("[bold]Correction attempts:[/bold]")
        for i, corr in enumerate(result.corrections, 1):
            layer = corr.get("layer", "unknown")
            success = corr.get("success", False)
            latency = corr.get("latency_ms")
            icon = "[green]✓[/green]" if success else "[red]✗[/red]"
            latency_str = f" ({latency:.0f}ms)" if latency else ""
            lines.append(f"  {icon} Layer {i}: {layer}{latency_str}")

    border = "green" if result.action == "pass" else "yellow" if result.action == "flag" else "red"
    console.print(Panel(
        "\n".join(lines),
        title="[bold]AgentGuard Verification[/bold]",
        border_style=border,
    ))
    thinking_pause(0.5)


def render_confidence_badge(result):
    """Render a compact confidence badge inline (for chat mode)."""
    if result is None or result.confidence is None:
        return
    color = _confidence_color(result.confidence)
    badge = _action_badge(result.action)
    console.print(
        f"  [{color}]●[/{color}] AgentGuard: {result.confidence:.0%} confidence — {badge}",
    )


def render_block_warning(result):
    """Render a prominent block warning panel."""
    score_str = f"{result.confidence:.0%}" if result.confidence is not None else "N/A"
    console.print(Panel(
        f"[bold red]Output blocked by AgentGuard[/bold red]\n\n"
        f"[bold]Confidence:[/bold] {score_str}\n"
        f"[bold]Action:[/bold] {_action_badge(result.action)}\n\n"
        "[dim]The response did not pass verification checks and was blocked.\n"
        "Please rephrase or try a different approach.[/dim]",
        title="[bold red]⛔ BLOCKED[/bold red]",
        border_style="red",
    ))


def step_present_campaign(show: dict, campaign: dict):
    """Step 5: Display the full campaign for review."""
    step_header(5, "Campaign ready for review")
    thinking_pause(0.5)

    # Segment panel
    seg = campaign["segment"]
    segment_text = (
        f'[bold]{seg["name"]}[/bold]\n'
        f'[dim]Reasoning:[/dim] {seg["reasoning"]}'
    )
    seg_count = next((s["count"] for s in SEGMENTS if s["name"] == seg["name"]), "?")
    segment_text += f'\n[dim]Contacts:[/dim] [bold]{seg_count}[/bold]'

    console.print(Panel(segment_text, title="[bold]📋 Target Segment[/bold]", border_style="blue"))

    # Copy options
    console.print()
    for opt in campaign["copy_options"]:
        char_count = len(opt["text"])
        color = "green" if char_count <= 140 else "red"
        opt_out_text = "\nReply STOP to unsubscribe"
        console.print(Panel(
            f'[bold]{opt["text"]}[/bold]\n'
            f'[dim italic]{opt_out_text.strip()}[/dim italic]\n\n'
            f'[dim]Angle:[/dim] {opt["angle"]}  •  '
            f'[{color}]{char_count} chars[/{color}] (+26 opt-out = {char_count + 26} total)',
            title=f"[bold]Option {opt['id']}[/bold]",
            border_style="yellow",
        ))

    # Send time
    st = campaign["send_time"]
    console.print(Panel(
        f'[bold]{st.get("day", "")} {st.get("date", "")}, {st["time"]}[/bold]\n'
        f'[dim]Reasoning:[/dim] {st["reasoning"]}',
        title="[bold]⏰ Recommended Send Time[/bold]",
        border_style="green",
    ))


def step_guardrails(campaign: dict) -> bool:
    """Step 6: Run safety guardrails."""
    step_header(6, "Running safety guardrails...")
    thinking_pause(0.8)

    checks = []

    # Quiet hours check
    send_time_str = campaign["send_time"]["time"].upper()
    checks.append(("Quiet hours (9pm-9am)", True, f"Send at {send_time_str} is within allowed window"))

    # Frequency cap
    if SCENARIO == "overlap":
        checks.append(("Frequency cap (4/month)", True, "Segment avg 1.2 msgs this month — under cap. Queued show will check again before sending."))
    else:
        checks.append(("Frequency cap (4/month)", True, "Segment avg 1.2 msgs this month — under cap"))

    # Opt-out footer
    checks.append(("Opt-out footer", True, "Auto-appended to all copy options"))

    # Blocked words check
    blocked_found = []
    for opt in campaign["copy_options"]:
        for word in VENUE["words_to_avoid"]:
            if word.lower() in opt["text"].lower():
                blocked_found.append((opt["id"], word))

    if blocked_found:
        details = ", ".join(f'Option {o}: "{w}"' for o, w in blocked_found)
        checks.append(("Blocked words", False, f"FOUND: {details}"))
    else:
        checks.append(("Blocked words", True, "None detected"))

    # Character limit
    over_limit = [opt for opt in campaign["copy_options"] if len(opt["text"]) > 160]
    if over_limit:
        checks.append(("Character limit (160)", False, f"Options {[o['id'] for o in over_limit]} exceed limit"))
    else:
        checks.append(("Character limit (160)", True, "All options within limit"))

    all_passed = True
    for name, passed, detail in checks:
        icon = "[green]✅[/green]" if passed else "[red]❌[/red]"
        console.print(f"  {icon} [bold]{name}:[/bold] {detail}")
        if not passed:
            all_passed = False
        thinking_pause(0.3)

    console.print()
    if all_passed:
        console.print("[bold green]All guardrails passed.[/bold green]")
    else:
        console.print("[bold yellow]⚠ Some guardrails flagged — review before approving.[/bold yellow]")

    return all_passed


def step_review(campaign: dict) -> tuple:
    """Step 7: Interactive review — user picks copy, can edit, approves."""
    step_header(7, "Your review")

    choice = IntPrompt.ask(
        "\n[bold]Select copy option[/bold]",
        choices=[str(o["id"]) for o in campaign["copy_options"]],
        default=1,
    )
    selected_copy = next(o for o in campaign["copy_options"] if o["id"] == choice)
    console.print(f'\n[dim]Selected:[/dim] [bold]"{selected_copy["text"]}"[/bold]\n')

    edit = Prompt.ask("[bold]Edit this copy?[/bold]", choices=["y", "n"], default="n")
    if edit == "y":
        new_text = Prompt.ask("[bold]Enter your edited copy[/bold]")
        if new_text.strip():
            selected_copy["text"] = new_text.strip()
            console.print(f'\n[dim]Updated to:[/dim] [bold]"{selected_copy["text"]}"[/bold]\n')

    approve = Prompt.ask(
        "[bold green]Approve & Schedule this campaign?[/bold green]",
        choices=["y", "n"],
        default="y",
    )

    return selected_copy, approve == "y"


def step_send(show: dict, campaign: dict, selected_copy: dict):
    """Step 8: Simulate sending and show results."""
    step_header(8, "Campaign approved — scheduling send")

    st = campaign["send_time"]
    seg = campaign["segment"]
    seg_count = next((s["count"] for s in SEGMENTS if s["name"] == seg["name"]), 300)

    console.print(Panel(
        f'[bold green]✓ CAMPAIGN SCHEDULED[/bold green]\n\n'
        f'[bold]Show:[/bold] {show["name"]}\n'
        f'[bold]Segment:[/bold] {seg["name"]} ({seg_count} contacts)\n'
        f'[bold]Copy:[/bold] "{selected_copy["text"]}"\n'
        f'[bold]Send Time:[/bold] {st.get("day", "")} {st.get("date", "")}, {st["time"]}\n'
        f'[bold]Opt-Out Footer:[/bold] Reply STOP to unsubscribe',
        title="[bold]📨 Confirmation[/bold]",
        border_style="green",
    ))

    thinking_pause(1.5)
    console.print()

    # Simulate results
    with console.status("[bold cyan]Simulating delivery results...[/bold cyan]", spinner="dots"):
        thinking_pause(2.0)

    sent = seg_count

    if SCENARIO == "spike":
        # Simulate bad results — opt-out spike
        delivered = int(sent * random.uniform(0.93, 0.96))
        clicked = int(delivered * random.uniform(0.08, 0.12))
        opted_out = int(sent * random.uniform(0.025, 0.035))  # 2.5-3.5% opt-out
        failed = sent - delivered
    else:
        delivered = int(sent * random.uniform(0.95, 0.99))
        clicked = int(delivered * random.uniform(0.18, 0.28))
        opted_out = random.randint(0, max(1, int(sent * 0.005)))
        failed = sent - delivered

    ctr = (clicked / delivered * 100) if delivered > 0 else 0
    opt_out_rate = (opted_out / sent * 100) if sent > 0 else 0

    results_table = Table(box=box.ROUNDED, title="Campaign Results (Simulated)")
    results_table.add_column("Metric", style="bold")
    results_table.add_column("Value", justify="right")
    results_table.add_column("Status", justify="center")

    results_table.add_row("Sent", str(sent), "")
    results_table.add_row("Delivered", str(delivered), f"[green]{delivered/sent*100:.1f}%[/green]")
    results_table.add_row("Clicked", str(clicked), f"[green]{ctr:.1f}% CTR[/green]" if ctr >= 15 else f"[yellow]{ctr:.1f}% CTR[/yellow]")
    results_table.add_row(
        "Opted Out", str(opted_out),
        f"[green]{opt_out_rate:.2f}%[/green]" if opt_out_rate < 1
        else f"[bold red]{opt_out_rate:.2f}% ⚠[/bold red]" if opt_out_rate >= 2
        else f"[red]{opt_out_rate:.2f}%[/red]"
    )
    results_table.add_row("Failed", str(failed), "")

    console.print(results_table)

    # Opt-out spike detection
    if opt_out_rate >= 2.0:
        console.print()
        console.print(Panel(
            f'[bold red]🚨 OPT-OUT SPIKE DETECTED[/bold red]\n\n'
            f'[bold]{opt_out_rate:.1f}% opt-out rate[/bold] exceeds the 2% safety threshold.\n\n'
            f'[bold]Automatic actions taken:[/bold]\n'
            f'  [red]■[/red] All pending campaigns for {VENUE["name"]} [bold]PAUSED[/bold]\n'
            f'  [red]■[/red] Alert sent to account manager\n'
            f'  [red]■[/red] Next [bold]5 campaigns require manual approval[/bold] (even if auto-send is enabled)\n\n'
            f'[bold]Recommended investigation:[/bold]\n'
            f'  • Review copy tone — was it too aggressive for this segment?\n'
            f'  • Check if segment included recently-contacted subscribers\n'
            f'  • Verify send time wasn\'t during an unusual hour\n\n'
            f'[dim]Agent will not send autonomously until opt-out rate returns below 1% for 30 days.[/dim]',
            title="[bold red]⛔ SAFETY CIRCUIT BREAKER[/bold red]",
            border_style="red",
        ))
    else:
        console.print()
        console.print(Panel(
            f'[bold cyan]🤖 Agent Learning:[/bold cyan]\n\n'
            f'• {ctr:.1f}% CTR — {"above" if ctr > 20 else "at"} average for {show["genre"]} campaigns\n'
            f'• {opt_out_rate:.2f}% opt-out rate — well within safe range (<1%)\n'
            f'• Will factor these results into future {show["genre"]} show targeting',
            border_style="cyan",
        ))


# ── Chat Mode ──────────────────────────────────────────────


def build_onboarding_system_prompt():
    """Build a system prompt for brand-new venues that need guided setup."""
    shows_text = ""
    for i, show in enumerate(SHOWS, 1):
        shows_text += (
            f"  {i}. {show['name']}\n"
            f"     Date: {show['date_full']} | Genre: {show['genre']} | "
            f"Sold: {show['tickets_pct']}% ({show['tickets_sold']}/{show['capacity']})\n"
        )

    total_subs = SEGMENTS[-1]["count"] if SEGMENTS else 0

    return f"""You are the Hive AI SMS Marketing Agent — an autonomous AI assistant that helps music venues create and manage targeted SMS marketing campaigns.

You are onboarding a BRAND NEW venue: **{VENUE['name']}** (capacity: {VENUE['capacity']}).

## CURRENT STATE — INCOMPLETE SETUP
This venue just signed up. Their profile is mostly empty:
- Name: {VENUE['name']}
- Capacity: {VENUE['capacity']}
- Brand voice: **NOT SET** — you need to help them define this
- Genres: **NOT SET** — you need to ask what music they book
- Words to avoid: **NOT SET** — you need to help them think about brand guardrails
- Preferred send days: **NOT SET** — you'll recommend based on industry data
- Preferred send hours: **NOT SET** — you'll recommend based on industry data
- Subscribers: {total_subs} (imported from an email list — no behavioral segmentation yet)
- Past campaigns: **NONE** — this will be their first SMS campaign ever

## SHOWS ALREADY ADDED
{shows_text}
## YOUR ONBOARDING MISSION
Guide this venue owner through their complete setup, step by step. You need to collect:

1. **Brand voice** — Ask about their venue's personality. Are they casual/fun, upscale/sophisticated, edgy/underground, friendly/community-focused? Give examples of how each voice sounds in an SMS.
2. **Genres** — Ask what kinds of music/events they host. This helps you match audience targeting later.
3. **Words to avoid** — Ask if there are words that don't fit their brand. Give examples: a classy jazz lounge might avoid "wild", "insane", "lit". A punk venue might avoid "elegant", "exclusive".
4. **Send preferences** — Recommend days/times based on industry benchmarks for their venue type. Music venue SMS best practices: Tuesday-Thursday, 12pm-2pm or 5pm-7pm.

After setup is complete, proactively offer to create their first campaign for their most urgent show.

## ONBOARDING RULES
- Ask ONE or TWO setup questions at a time — don't overwhelm them with a wall of questions
- After each answer, confirm what you understood and save it, then move to the next question
- Use industry benchmarks since there's no historical data:
  - Average SMS CTR for music venues: 15-22%
  - Average opt-out rate: 0.3-0.8%
  - Best send times: Tuesday-Thursday, lunch (12-2pm) or evening (5-7pm)
  - First campaigns should be conservative: send to all subscribers, single send, full approval flow
- Be warm and encouraging — this is their first time using AI marketing
- When they finish setup, summarize everything and transition to campaign creation
- For their first campaign, be more hand-holding: explain every decision, show your reasoning clearly
- Recommend starting with their most urgent show
- After their first campaign, explain how the system gets smarter: "After 3 campaigns, I'll have enough data to start recommending segments and optimizing send times automatically"

## PROGRESSIVE AUTONOMY EXPLANATION
When relevant, explain the trust ladder:
- **Campaigns 1-3**: Full human-in-the-loop. You suggest everything, they approve everything.
- **Campaigns 4-10**: Agent can auto-select segments and timing, but copy still needs approval.
- **Campaigns 10+**: Agent can auto-send routine campaigns (re-engagement, low-urgency). High-stakes campaigns still require approval.
- The venue owner can adjust these thresholds anytime.

## RESPONSE STYLE
- Be conversational, warm, and encouraging — they're new and might be nervous about AI managing their marketing
- Use markdown formatting for readability
- Keep responses focused — one topic at a time
- Celebrate small wins ("Great choice! That brand voice will really resonate with your audience")
- When generating their first campaign, walk through every decision in detail"""


def build_chat_system_prompt():
    """Build a comprehensive system prompt with all venue data for conversational mode."""
    # Detect onboarding state — no brand voice means unconfigured venue
    if SCENARIO == "onboarding" or (not VENUE.get("brand_voice") and not VENUE.get("genres")):
        return build_onboarding_system_prompt()

    shows_text = ""
    for i, show in enumerate(SHOWS, 1):
        urgency = "HIGH" if show["tickets_pct"] < 50 else "MEDIUM" if show["tickets_pct"] < 75 else "LOW"
        shows_text += (
            f"  {i}. {show['name']}\n"
            f"     Date: {show['date_full']} | Genre: {show['genre']} | "
            f"Sold: {show['tickets_pct']}% ({show['tickets_sold']}/{show['capacity']}) | "
            f"Urgency: {urgency}\n"
        )

    segments_text = ""
    for seg in SEGMENTS:
        segments_text += f"  - {seg['name']} ({seg['count']} contacts): {seg['description']}\n"

    past_text = ""
    if PAST_CAMPAIGNS:
        for camp in PAST_CAMPAIGNS:
            past_text += (
                f"  - {camp['show']} → {camp['segment']}: "
                f"{camp['sent']} sent, {camp['ctr']} CTR, {camp['opted_out']} opt-outs\n"
            )
    else:
        past_text = "  No past campaigns yet (new venue).\n"

    total_subs = SEGMENTS[-1]["count"] if SEGMENTS else 0
    small_venue_note = ""
    if total_subs < 100:
        small_venue_note = f"""
## SMALL VENUE ADVISORY
This venue has only {total_subs} contacts. With fewer than 100 subscribers:
- Skip segmentation — send to all subscribers
- Use industry best practices instead of historical data (not enough data to be statistically meaningful)
- Apply conservative frequency (max 2/month until audience grows)
- Mention this proactively when discussing campaign strategy
"""

    return f"""You are the Hive AI SMS Marketing Agent — an autonomous AI assistant that helps music venues create and manage targeted SMS marketing campaigns to sell more tickets.

You are currently managing: **{VENUE['name']}**

## YOUR CAPABILITIES
1. **Analyze** upcoming shows and identify which need promotional campaigns (prioritize by urgency — lowest ticket sales first)
2. **Target** the optimal audience segment based on show genre, past performance, and segment behavior
3. **Generate** SMS copy options (each MUST be ≤140 characters) that match the venue's brand voice
4. **Recommend** optimal send times based on venue preferences and historical data
5. **Enforce** safety guardrails: quiet hours, frequency caps, blocked words, opt-out compliance
6. **Schedule** campaigns with human-in-the-loop approval

## VENUE PROFILE
- Name: {VENUE['name']}
- Capacity: {VENUE['capacity']}
- Brand voice: {VENUE['brand_voice']}
- Genres: {', '.join(VENUE['genres'])}
- Words to NEVER use in copy: {', '.join(f'"{w}"' for w in VENUE['words_to_avoid'])}
- Preferred send days: {', '.join(VENUE['preferred_send_days'])}
- Preferred send hours: {VENUE['preferred_send_hours']}
- Quiet hours (no sending allowed): {VENUE['quiet_hours_start']} - {VENUE['quiet_hours_end']}
- Max messages per subscriber: {VENUE['max_monthly_messages']}/month

## UPCOMING SHOWS
{shows_text}
## AUDIENCE SEGMENTS
{segments_text}
## PAST CAMPAIGN PERFORMANCE
{past_text}
{small_venue_note}
## RULES YOU MUST FOLLOW
1. Every SMS copy option must be ≤140 characters (opt-out footer "Reply STOP to unsubscribe" is appended separately — do NOT include it in the copy)
2. NEVER use words from the venue's avoid list: {', '.join(f'"{w}"' for w in VENUE['words_to_avoid'])}
3. NEVER suggest sending during quiet hours ({VENUE['quiet_hours_start']}-{VENUE['quiet_hours_end']})
4. Respect the frequency cap of {VENUE['max_monthly_messages']} messages/month per subscriber
5. When generating copy, always provide exactly 3 options with different creative angles
6. Show character count for each SMS option
7. When recommending timing, explain your reasoning referencing actual past data

## RESPONSE STYLE
- Be conversational but professional and concise
- Use markdown formatting: **bold** for emphasis, numbered lists for options, bullet points for details
- When presenting SMS copy options, number them clearly and show character count in parentheses
- Be proactive — after completing a task, suggest the natural next step
- If a request would violate a guardrail, explain why and offer an alternative
- Show your reasoning — venue owners trust agents that explain their thinking
- When running guardrail checks, list each check clearly with PASS or FAIL status"""


def call_chat_llm(system_prompt, messages):
    """Call OpenRouter with full conversation history for chat mode.

    Returns:
        A tuple of (content_str, usage_dict) where usage_dict may be None.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in .env")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hive.co",
        "X-Title": "Hive AI SMS Agent Demo",
    }

    payload = {
        "model": "x-ai/grok-4.1-fast",
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    response = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()

    raw_body = response.text.strip()
    body = json.loads(raw_body)
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage")

    if not content or not content.strip():
        raise ValueError("Empty response from model")

    return content.strip(), usage


def render_agent_response(text):
    """Render the agent's response with rich markdown formatting."""
    console.print()
    try:
        md = Markdown(text)
        console.print(Panel(
            md,
            title="[bold cyan]Hive AI[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
    except Exception:
        console.print(Panel(
            text,
            title="[bold cyan]Hive AI[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))


def chat_mode():
    """Run the agent in conversational chat mode."""
    global SCENARIO

    if not USE_API:
        console.print("[bold red]Chat mode requires API access. Remove --no-api flag to use chat mode.[/bold red]")
        sys.exit(1)

    console.clear()
    console.print()
    console.print(Panel(
        "[bold white]Hive AI SMS Marketing Agent[/bold white]\n"
        "[dim]Conversational mode — talk to your AI marketing agent naturally[/dim]\n\n"
        "[dim italic]Type 'exit' to quit  |  Ctrl+C to force quit[/dim italic]",
        title="[bold]HIVE AI — Chat Mode[/bold]",
        border_style="bright_blue",
        padding=(1, 2),
    ))

    # Let user pick a venue/scenario context
    SCENARIO = show_scenario_picker()
    apply_scenario()

    system_prompt = build_chat_system_prompt()
    conversation = []

    # Create a session for this conversation
    session = guard.session(
        agent_id=AGENT_ID,
        metadata={"mode": "chat", "venue": VENUE["name"], "scenario": SCENARIO},
    )

    # Generate initial greeting — different prompt for onboarding vs. regular
    if SCENARIO == "onboarding":
        initial_message = (
            "Hi! I just signed up and imported my email list. "
            "This is my first time using an AI marketing tool — help me get started."
        )
    else:
        initial_message = (
            "I just opened the dashboard. Give me a quick status update — "
            "what venue am I looking at, which shows need attention most urgently, "
            "and what do you recommend I do first?"
        )

    conversation.append({"role": "user", "content": initial_message})

    try:
        with console.status("[bold cyan]Agent loading your venue data...[/bold cyan]", spinner="dots"):
            t0 = time.monotonic()
            greeting, usage = call_chat_llm(system_prompt, conversation)
            llm_ms = (time.monotonic() - t0) * 1000

        blocked = False
        try:
            with session.trace(
                task=f"chat: initial greeting ({VENUE['name']})",
                input_data={"message": initial_message, "venue": VENUE["name"]},
            ) as ctx:
                ctx.step("llm", "chat_response", input=initial_message, output=greeting[:500], duration_ms=llm_ms)
                if usage:
                    total_tokens = usage.get("total_tokens") or (
                        (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
                    )
                    if total_tokens:
                        ctx.set_token_count(total_tokens)
                        ctx.set_cost_estimate(total_tokens * 0.000002)
                ctx.record(greeting[:500])
        except AgentGuardBlockError as e:
            blocked = True
            render_block_warning(e.result)

        if not blocked:
            conversation.append({"role": "assistant", "content": greeting})
            render_agent_response(greeting)
            if hasattr(ctx, "result") and ctx.result and ctx.result.confidence is not None:
                render_confidence_badge(ctx.result)
        else:
            # Greeting was blocked — show fallback and continue
            console.print("[dim]Initial greeting was blocked. Continuing without it.[/dim]")

    except Exception as e:
        console.print(f"\n[bold red]Failed to connect to AI: {e}[/bold red]")
        console.print("[dim]Check your OPENROUTER_API_KEY in .env and try again.[/dim]")
        return

    console.print()
    console.print(
        "[dim]Try asking: \"Create a campaign for [show name]\"  |  "
        "\"What segment should I target?\"  |  "
        "\"Check guardrails on this copy\"[/dim]"
    )

    try:
        while True:
            console.print()
            user_input = Prompt.ask("[bold green]You[/bold green]")

            if not user_input.strip():
                continue

            if user_input.lower().strip() in ("exit", "quit", "bye"):
                break

            conversation.append({"role": "user", "content": user_input})

            with console.status("[bold cyan]Agent thinking...[/bold cyan]", spinner="dots"):
                try:
                    t0 = time.monotonic()
                    response, usage = call_chat_llm(system_prompt, conversation)
                    llm_ms = (time.monotonic() - t0) * 1000
                except Exception as e:
                    console.print(f"\n[bold red]Error: {e}[/bold red]")
                    conversation.pop()  # Remove the failed user message
                    continue

            blocked = False
            try:
                with session.trace(
                    task=f"chat: {user_input[:80]}",
                    input_data={"message": user_input, "turn": session.sequence},
                ) as ctx:
                    ctx.step("llm", "chat_response", input=user_input, output=response[:500], duration_ms=llm_ms)
                    if usage:
                        total_tokens = usage.get("total_tokens") or (
                            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
                        )
                        if total_tokens:
                            ctx.set_token_count(total_tokens)
                            ctx.set_cost_estimate(total_tokens * 0.000002)
                    ctx.record(response[:500])
            except AgentGuardBlockError as e:
                blocked = True
                render_block_warning(e.result)

            if not blocked:
                conversation.append({"role": "assistant", "content": response})
                render_agent_response(response)
                if hasattr(ctx, "result") and ctx.result and ctx.result.confidence is not None:
                    render_confidence_badge(ctx.result)
            else:
                # Remove the user message that led to blocked output
                conversation.pop()
                console.print("[dim]Response was blocked. Please try rephrasing your request.[/dim]")

    except KeyboardInterrupt:
        pass

    if guard is not None:
        guard.close()
    console.print()
    console.print(Panel(
        "[bold]Chat session ended.[/bold]\n"
        "[dim]All scheduled campaigns will send as planned.[/dim]",
        border_style="blue",
    ))


# ── Main ────────────────────────────────────────────────────

SCENARIO_DESCRIPTIONS = {
    "default": "Standard flow — Miller Theater, everything works as expected",
    "guardrail": "AI generates copy with blocked words — guardrails catch it",
    "small": "Tiny venue with 47 contacts — cold start graceful degradation",
    "spike": "Campaign triggers opt-out spike — safety circuit breaker fires",
    "overlap": "Two jazz shows same week — audience overlap detection",
    "onboarding": "Brand new venue, zero history — guided first-time setup + first campaign",
}


def show_scenario_picker() -> str:
    """Display available scenarios and let user pick one."""
    console.print()
    console.print(Panel(
        "[bold]Available Scenarios[/bold]",
        border_style="bright_blue",
    ))

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Scenario", style="bold", width=14)
    table.add_column("Description", width=60)

    scenario_list = list(SCENARIO_DESCRIPTIONS.items())
    for i, (key, desc) in enumerate(scenario_list, 1):
        table.add_row(str(i), key, desc)

    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[bold]Select scenario[/bold]",
        choices=[str(i) for i in range(1, len(scenario_list) + 1)],
        default="1",
    )
    return scenario_list[int(choice) - 1][0]


def run_campaign():
    """Run a single campaign flow."""
    apply_scenario()

    console.clear()
    console.print()
    console.print(Panel(
        "[bold white]Hive AI SMS Marketing Agent[/bold white]\n"
        "[dim]Autonomous campaign creation for music venues[/dim]",
        title="[bold]🎵 HIVE AI[/bold]",
        border_style="bright_blue",
        padding=(1, 2),
    ))

    if SCENARIO != "default":
        console.print(Panel(
            f'[bold]Scenario:[/bold] {SCENARIO}\n'
            f'[dim]{SCENARIO_DESCRIPTIONS[SCENARIO]}[/dim]',
            border_style="magenta",
        ))

    console.print()
    thinking_pause(1.0)

    with guard.trace(
        agent_id=AGENT_ID,
        task=f"SMS campaign: {VENUE['name']} ({SCENARIO})",
        input_data={"scenario": SCENARIO, "venue": VENUE["name"]},
    ) as ctx:
        # Step 1: Load venue
        t0 = time.monotonic()
        step_load_venue()
        ctx.step(
            "tool_call", "load_venue",
            input={"venue": VENUE["name"]},
            output={"segments": len(SEGMENTS), "subscribers": SEGMENTS[-1]["count"] if SEGMENTS else 0},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

        # Step 2: Scan shows
        t0 = time.monotonic()
        step_scan_shows()
        ctx.step(
            "tool_call", "scan_shows",
            input=None,
            output={"count": len(SHOWS), "shows": [s["name"] for s in SHOWS]},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

        # Step 3: Select best opportunity
        t0 = time.monotonic()
        selected_show = step_select_show()
        ctx.step(
            "custom", "select_show",
            input={"candidates": len(SHOWS)},
            output={"selected": selected_show["name"], "tickets_pct": selected_show["tickets_pct"]},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

        # Step 4: Generate campaign via LLM (+ AgentGuard verification)
        t0 = time.monotonic()
        campaign, usage, guard_result = step_generate_campaign(selected_show)
        step4_ms = (time.monotonic() - t0) * 1000
        ctx.step(
            "llm", "generate_campaign",
            input={"show": selected_show["name"], "venue": VENUE["name"]},
            output=campaign,
            duration_ms=step4_ms,
        )
        if usage:
            total_tokens = usage.get("total_tokens") or (
                (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
            )
            if total_tokens:
                ctx.set_token_count(total_tokens)
                ctx.set_cost_estimate(total_tokens * 0.000002)
                ctx.set_metadata("model", "x-ai/grok-4.1-fast")

        # Step 4b: Show verification results (sync mode only)
        step_verify_result(guard_result)

        # Handle block — verification rejected the output
        if guard_result and guard_result.action == "block":
            ctx.record({
                "status": "blocked",
                "show": selected_show["name"],
                "confidence": guard_result.confidence,
            })
            console.print(Panel(
                "[bold red]Campaign blocked by AgentGuard verification.[/bold red]\n\n"
                "[dim]The generated campaign did not meet the confidence threshold.\n"
                "Skipping remaining steps. Try again or adjust thresholds.[/dim]",
                title="[bold red]⛔ CAMPAIGN BLOCKED[/bold red]",
                border_style="red",
            ))
            return

        # Handle flag — verification raised a warning but allows continuation
        if guard_result and guard_result.action == "flag":
            console.print(Panel(
                "[bold yellow]⚠ AgentGuard flagged this output for review.[/bold yellow]\n\n"
                "[dim]The confidence score is below the pass threshold but above block.\n"
                "Proceeding with the campaign — please review carefully.[/dim]",
                title="[bold yellow]⚠ FLAGGED[/bold yellow]",
                border_style="yellow",
            ))

        # Handle correction — use the corrected campaign if applicable
        if guard_result and guard_result.corrected:
            campaign = guard_result.output
            console.print("[cyan]Using auto-corrected campaign output.[/cyan]\n")

        # Step 5: Present campaign
        step_present_campaign(selected_show, campaign)

        # Step 6: Run guardrails
        t0 = time.monotonic()
        guardrails_passed = step_guardrails(campaign)
        ctx.step(
            "custom", "guardrails_check",
            input={"copy_options": len(campaign.get("copy_options", []))},
            output={"all_passed": guardrails_passed},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

        # Step 7: User review
        t0 = time.monotonic()
        selected_copy, approved = step_review(campaign)
        ctx.step(
            "custom", "human_review",
            input={"copy": selected_copy["text"]},
            output={"approved": approved, "selected_option": selected_copy["id"]},
            duration_ms=(time.monotonic() - t0) * 1000,
        )

        if approved:
            # Step 8: Send and show results
            t0 = time.monotonic()
            step_send(selected_show, campaign, selected_copy)
            ctx.step(
                "custom", "send_campaign",
                input={"segment": campaign["segment"]["name"], "show": selected_show["name"]},
                output={"status": "scheduled"},
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            ctx.record({
                "status": "approved",
                "show": selected_show["name"],
                "segment": campaign["segment"]["name"],
                "copy": selected_copy["text"],
            })
        else:
            ctx.record({"status": "cancelled", "show": selected_show["name"]})
            console.print("\n[bold yellow]Campaign cancelled.[/bold yellow] Agent will refine and suggest again.\n")


def main():
    """Main loop — runs scenarios continuously until Ctrl+C."""
    global SCENARIO

    console.clear()
    console.print()

    # Show mode info
    mode_parts = []
    if SYNC_MODE:
        mode_parts.append("[bold cyan]sync verification[/bold cyan]")
    else:
        mode_parts.append("[dim]async telemetry[/dim]")
    if CORRECTION_MODE:
        mode_parts.append("[bold cyan]correction cascade[/bold cyan]")
    mode_str = " + ".join(mode_parts)

    console.print(Panel(
        "[bold white]Hive AI SMS Marketing Agent[/bold white]\n"
        "[dim]Autonomous campaign creation for music venues[/dim]\n\n"
        f"[bold]Mode:[/bold] {mode_str}\n"
        "[dim italic]Press Ctrl+C at any time to exit[/dim italic]",
        title="[bold]🎵 HIVE AI[/bold]",
        border_style="bright_blue",
        padding=(1, 2),
    ))

    try:
        while True:
            # Pick scenario
            SCENARIO = show_scenario_picker()

            # Run the campaign flow
            run_campaign()

            # After campaign completes, prompt to continue
            console.print()
            console.print(Panel(
                "[bold green]Campaign complete.[/bold green]\n"
                "[dim]Ready for the next scenario.[/dim]",
                border_style="green",
            ))
            thinking_pause(1.0)

    except KeyboardInterrupt:
        if guard is not None:
            guard.close()
        console.print("\n")
        console.print(Panel(
            "[bold]Agent shutting down.[/bold]\n"
            "[dim]All scheduled campaigns will send as planned.[/dim]",
            border_style="blue",
        ))
        console.print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hive AI SMS Marketing Agent Demo")
    parser.add_argument("--no-api", action="store_true", help="Run without API calls (uses fallback campaign data)")
    parser.add_argument("--chat", action="store_true", help="Run in conversational chat mode")
    parser.add_argument("--sync", action="store_true", help="Use sync verification mode (inline verification before returning)")
    parser.add_argument("--correction", action="store_true", help="Enable correction cascade (auto-correct flagged outputs)")
    args = parser.parse_args()

    if args.no_api:
        USE_API = False
    if args.sync:
        SYNC_MODE = True
    if args.correction:
        CORRECTION_MODE = True

    build_guard()

    if args.chat:
        chat_mode()
    else:
        main()
