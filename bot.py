import json
import os
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv

# =========================
# LOAD ENV
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# =========================
# CONFIG
# =========================
DATA_FILE = "clock_data.json"

GUILD_ID = 1468026432738299916

EMPLOYEE_ROLE_NAME = "Purple Haze Employee"
MANAGER_ROLE_NAME = "Purple Haze Manager"
LOA_ROLE_NAME = "LOA"

PAYROLL_ROLE_NAMES = [
    "🛎️ Restaurant Manager",
    "🍸 Bartender",
    "🍛 Server",
]

LEADERBOARD_ROLE_NAMES = [
    "🧰 Head Mechanic",
    "🛠️ Mechanic",
    "🔧 Apprentice",
    "🛎️ Restaurant Manager",
    "🍸 Bartender",
    "🍛 Server",
]

HOURLY_RATES = {
    "🛎️ Restaurant Manager": 1000,
    "🍸 Bartender": 800,
    "🍛 Server": 700,
}

TIMECLOCK_CHANNEL_NAME = "⏲️│timeclock"
TIMECLOCK_REMINDER_CHANNEL_NAME = "⌚│timeclock-reminder"
CHECKING_HOURS_CHANNEL_NAME = "🕛│checking-hours"
FIXING_HOURS_CHANNEL_NAME = "⏰│fixing-hours"
PAYROLL_TRACKING_CHANNEL_NAME = "💰│payroll-tracking"
LEADERBOARD_CHANNEL_NAME = "🏆│leaderboard"
LEAVE_OF_ABSENCE_CHANNEL_NAME = "🏝️│leave-of-absence"

try:
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    PACIFIC_TZ = timezone.utc

PURPLE = discord.Color.from_rgb(128, 0, 128)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATA HELPERS
# =========================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def ensure_user(data, member: discord.Member):
    user_id = str(member.id)
    if user_id not in data:
        data[user_id] = {
            "name": member.display_name,
            "clocked_in": None,
            "total_seconds": 0,
            "weekly_seconds": 0,
            "last_reminder_hour": 0
        }
    else:
        data[user_id]["name"] = member.display_name
        data[user_id].setdefault("clocked_in", None)
        data[user_id].setdefault("total_seconds", 0)
        data[user_id].setdefault("weekly_seconds", 0)
        data[user_id].setdefault("last_reminder_hour", 0)
    return user_id

def format_seconds(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours}h {minutes}m"

def format_money(amount: float) -> str:
    return f"${amount:,.2f}"

def seconds_to_hours(seconds: int) -> float:
    return seconds / 3600

def has_role(member: discord.Member, role_name: str) -> bool:
    return any(role.name == role_name for role in member.roles)

def is_on_loa(member: discord.Member) -> bool:
    return has_role(member, LOA_ROLE_NAME)

def get_member_role_name_from_list(member: discord.Member, role_names: list[str]) -> str | None:
    for role_name in role_names:
        if has_role(member, role_name):
            return role_name
    return None

def get_channel_by_name(guild: discord.Guild, channel_name: str):
    return discord.utils.get(guild.text_channels, name=channel_name)

def make_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=PURPLE)
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Purple Haze Garage & Grill")
    return embed

def current_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def calculate_live_totals(info: dict) -> tuple[int, int]:
    total_seconds = int(info.get("total_seconds", 0))
    weekly_seconds = int(info.get("weekly_seconds", 0))

    if info.get("clocked_in"):
        start = datetime.fromisoformat(info["clocked_in"])
        worked = int((datetime.now(timezone.utc) - start).total_seconds())
        total_seconds += worked
        weekly_seconds += worked

    return total_seconds, weekly_seconds

def calculate_pay_for_role(role_name: str | None, seconds: int) -> float:
    if not role_name:
        return 0.0
    rate = HOURLY_RATES.get(role_name, 0)
    return seconds_to_hours(seconds) * rate

async def send_channel_embed(guild: discord.Guild, channel_name: str, embed: discord.Embed):
    channel = get_channel_by_name(guild, channel_name)
    if channel:
        await channel.send(embed=embed)

# =========================
# LEADERBOARD BUILDERS
# =========================
def build_pretty_role_columns(guild: discord.Guild, data: dict, role_name: str) -> tuple[str, str]:
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        return "_Role not found_", "_Role not found_"

    members_in_role = [m for m in guild.members if role in m.roles and not m.bot and not is_on_loa(m)]

    if not members_in_role:
        return "_No members_", "_No members_"

    weekly_list = []
    all_time_list = []

    for member in members_in_role:
        user_id = str(member.id)
        info = data.get(user_id, {
            "name": member.display_name,
            "total_seconds": 0,
            "weekly_seconds": 0,
            "clocked_in": None,
            "last_reminder_hour": 0
        })
        total_seconds, weekly_seconds = calculate_live_totals(info)
        weekly_list.append((member.display_name, weekly_seconds))
        all_time_list.append((member.display_name, total_seconds))

    weekly_list.sort(key=lambda x: x[1], reverse=True)
    all_time_list.sort(key=lambda x: x[1], reverse=True)

    weekly_text = "\n".join(
        f"**{name}**\n`{format_seconds(secs)}`"
        for name, secs in weekly_list
    )
    all_time_text = "\n".join(
        f"**{name}**\n`{format_seconds(secs)}`"
        for name, secs in all_time_list
    )

    return weekly_text[:1024], all_time_text[:1024]

def build_leaderboard_embeds(guild: discord.Guild, data: dict) -> list[discord.Embed]:
    embeds = []

    roles_per_embed = 2
    role_groups = [
        LEADERBOARD_ROLE_NAMES[i:i + roles_per_embed]
        for i in range(0, len(LEADERBOARD_ROLE_NAMES), roles_per_embed)
    ]

    for idx, group in enumerate(role_groups, start=1):
        embed = make_embed("💜Purple Haze Leaderboard🥇")
        embed.description = "Weekly Time on the left • ALL Time on the right"

        for role_name in group:
            weekly_text, all_time_text = build_pretty_role_columns(guild, data, role_name)

            embed.add_field(
                name=f"{role_name} — Weekly Time",
                value=weekly_text or "_No data_",
                inline=True
            )
            embed.add_field(
                name=f"{role_name} — ALL Time",
                value=all_time_text or "_No data_",
                inline=True
            )
            embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.set_footer(text=f"Purple Haze Garage & Grill • Page {idx}/{len(role_groups)}")
        embeds.append(embed)

    return embeds

def build_allhours_text(guild: discord.Guild, data: dict) -> str:
    lines = []
    members = [
        m for m in guild.members
        if not m.bot
        and has_role(m, EMPLOYEE_ROLE_NAME)
        and not is_on_loa(m)
    ]

    for member in members:
        user_id = str(member.id)
        info = data.get(user_id, {
            "name": member.display_name,
            "total_seconds": 0,
            "weekly_seconds": 0,
            "clocked_in": None,
            "last_reminder_hour": 0
        })
        total_seconds, weekly_seconds = calculate_live_totals(info)
        lines.append(
            f"**{member.display_name}** — Weekly: {format_seconds(weekly_seconds)} | All Time: {format_seconds(total_seconds)}"
        )

    if not lines:
        return "No employee hour records found."

    lines.sort()
    return "\n".join(lines)

# =========================
# PAYROLL BUILDERS
# =========================
def build_payroll_summary_embeds(guild: discord.Guild, data: dict) -> list[discord.Embed]:
    embeds = []

    for role_name in PAYROLL_ROLE_NAMES:
        role = discord.utils.get(guild.roles, name=role_name)
        embed = make_embed("Payroll Summary", f"**{role_name}** weekly paycheck totals by Discord name")

        if not role:
            embed.add_field(name="Status", value="Role not found.", inline=False)
            embeds.append(embed)
            continue

        members_in_role = [m for m in guild.members if role in m.roles and not m.bot and not is_on_loa(m)]

        if not members_in_role:
            embed.add_field(name="Status", value="No members in this role.", inline=False)
            embeds.append(embed)
            continue

        payroll_rows = []
        total_role_pay = 0.0

        for member in members_in_role:
            user_id = str(member.id)
            info = data.get(user_id, {
                "name": member.display_name,
                "total_seconds": 0,
                "weekly_seconds": 0,
                "clocked_in": None,
                "last_reminder_hour": 0
            })
            _, weekly_seconds = calculate_live_totals(info)
            weekly_pay = calculate_pay_for_role(role_name, weekly_seconds)
            total_role_pay += weekly_pay
            payroll_rows.append((member.display_name, weekly_seconds, weekly_pay))

        payroll_rows.sort(key=lambda x: x[2], reverse=True)

        chunk = ""
        for name, secs, pay in payroll_rows:
            line = f"**{name}**\nWeekly: `{format_seconds(secs)}` • Paycheck: `{format_money(pay)}`"
            if len(chunk) + len(line) + 1 > 1024:
                embed.add_field(name="Employees", value=chunk, inline=False)
                chunk = line
            else:
                chunk = f"{chunk}\n{line}".strip()

        if chunk:
            embed.add_field(name="Employees", value=chunk, inline=False)

        embed.add_field(
            name="Role Rate",
            value=f"{format_money(HOURLY_RATES.get(role_name, 0))}/hr",
            inline=True
        )
        embed.add_field(
            name="Role Total",
            value=format_money(total_role_pay),
            inline=True
        )
        embeds.append(embed)

    return embeds

# =========================
# SCHEDULED TASKS
# =========================
@tasks.loop(time=time(hour=20, minute=58, tzinfo=PACIFIC_TZ))
async def weekly_payroll_post():
    now_local = datetime.now(PACIFIC_TZ)
    if now_local.weekday() != 6:
        return

    for guild in bot.guilds:
        data = load_data()
        payroll_channel = get_channel_by_name(guild, PAYROLL_TRACKING_CHANNEL_NAME)
        if payroll_channel:
            embeds = build_payroll_summary_embeds(guild, data)
            for embed in embeds:
                await payroll_channel.send(embed=embed)

@weekly_payroll_post.before_loop
async def before_weekly_payroll_post():
    await bot.wait_until_ready()

@tasks.loop(time=time(hour=20, minute=59, tzinfo=PACIFIC_TZ))
async def weekly_leaderboard_post_and_reset():
    now_local = datetime.now(PACIFIC_TZ)
    if now_local.weekday() != 6:
        return

    for guild in bot.guilds:
        data = load_data()
        leaderboard_channel = get_channel_by_name(guild, LEADERBOARD_CHANNEL_NAME)

        if leaderboard_channel:
            embeds = build_leaderboard_embeds(guild, data)
            for embed in embeds:
                await leaderboard_channel.send(embed=embed)

        for user_id in data:
            data[user_id]["weekly_seconds"] = 0
            data[user_id]["last_reminder_hour"] = 0

            if data[user_id].get("clocked_in") is not None:
                data[user_id]["clocked_in"] = datetime.now(timezone.utc).isoformat()

        save_data(data)

        reset_embed = make_embed(
            "Weekly Hours Reset",
            "Weekly hours have been reset for the new week."
        )

        if leaderboard_channel:
            await leaderboard_channel.send(embed=reset_embed)

        payroll_channel = get_channel_by_name(guild, PAYROLL_TRACKING_CHANNEL_NAME)
        if payroll_channel:
            await payroll_channel.send(embed=reset_embed)

@weekly_leaderboard_post_and_reset.before_loop
async def before_weekly_leaderboard_post_and_reset():
    await bot.wait_until_ready()

@tasks.loop(minutes=1)
async def hourly_clockin_reminders():
    data = load_data()
    changed = False

    for guild in bot.guilds:
        reminder_channel = get_channel_by_name(guild, TIMECLOCK_REMINDER_CHANNEL_NAME)
        if not reminder_channel:
            continue

        reminder_members = []

        for member in guild.members:
            if member.bot:
                continue
            if is_on_loa(member):
                continue

            user_id = str(member.id)
            if user_id not in data:
                continue

            info = data[user_id]
            if not info.get("clocked_in"):
                continue

            try:
                start = datetime.fromisoformat(info["clocked_in"])
            except Exception:
                continue

            worked_seconds = int((datetime.now(timezone.utc) - start).total_seconds())
            completed_hours = worked_seconds // 3600
            last_sent = int(info.get("last_reminder_hour", 0))

            if completed_hours >= 1 and completed_hours > last_sent:
                reminder_members.append((member, start, worked_seconds, completed_hours))

        if not reminder_members:
            continue

        mentions = " ".join(member.mention for member, _, _, _ in reminder_members)

        blocks = []
        for member, start, worked_seconds, completed_hours in reminder_members:
            clock_in_unix = int(start.timestamp())
            block = (
                f"{member.mention} — **{member.display_name}**\n"
                f"Clocked in: <t:{clock_in_unix}:F>\n"
                f"Time clocked in: `{format_seconds(worked_seconds)}`\n"
                f"Completed hours: `{completed_hours}`"
            )
            blocks.append((member, block, completed_hours))

        pages = []
        current_page = ""

        for _, block, _ in blocks:
            addition = f"\n\n{block}" if current_page else block
            if len(current_page) + len(addition) > 4000:
                pages.append(current_page)
                current_page = block
            else:
                current_page += addition

        if current_page:
            pages.append(current_page)

        for index, page in enumerate(pages, start=1):
            embed = make_embed(
                "⌚ Timeclock Reminder",
                "The following employees are still clocked in:"
            )
            embed.add_field(
                name=f"Clocked In Employees ({index}/{len(pages)})",
                value=page,
                inline=False
            )

            if index == 1:
                await reminder_channel.send(content=mentions, embed=embed)
            else:
                await reminder_channel.send(embed=embed)

        for member, _, _, completed_hours in reminder_members:
            user_id = str(member.id)
            data[user_id]["last_reminder_hour"] = completed_hours
            changed = True

    if changed:
        save_data(data)

@hourly_clockin_reminders.before_loop
async def before_hourly_clockin_reminders():
    await bot.wait_until_ready()

# =========================
# BUTTON TIMECLOCK PANEL
# =========================
class TimeclockView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Clock In", style=discord.ButtonStyle.success, custom_id="timeclock_clockin")
    async def clock_in_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        if not has_role(member, EMPLOYEE_ROLE_NAME):
            await interaction.followup.send("You do not have the **Purple Haze Employee** role.", ephemeral=True)
            return

        if is_on_loa(member):
            await interaction.followup.send("You are currently marked as **LOA** and cannot clock in.", ephemeral=True)
            return

        data = load_data()
        user_id = ensure_user(data, member)

        if data[user_id]["clocked_in"] is not None:
            await interaction.followup.send("⚠️ You're already clocked in.", ephemeral=True)
            return

        data[user_id]["clocked_in"] = datetime.now(timezone.utc).isoformat()
        data[user_id]["last_reminder_hour"] = 0
        save_data(data)

        embed = make_embed(
            "Clocked In",
            f"{member.mention} clocked in at **Purple Haze Garage & Grill**."
        )
        embed.add_field(name="Employee", value=member.display_name, inline=True)
        embed.add_field(name="Time", value=f"<t:{current_unix()}:F>", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)
        await send_channel_embed(interaction.guild, TIMECLOCK_CHANNEL_NAME, embed)

    @discord.ui.button(label="Clock Out", style=discord.ButtonStyle.danger, custom_id="timeclock_clockout")
    async def clock_out_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        if not has_role(member, EMPLOYEE_ROLE_NAME):
            await interaction.followup.send("You do not have the **Purple Haze Employee** role.", ephemeral=True)
            return

        data = load_data()
        user_id = ensure_user(data, member)

        if data[user_id]["clocked_in"] is None:
            await interaction.followup.send("⚠️ You're not clocked in.", ephemeral=True)
            return

        start = datetime.fromisoformat(data[user_id]["clocked_in"])
        end = datetime.now(timezone.utc)
        worked = int((end - start).total_seconds())

        data[user_id]["total_seconds"] += worked
        data[user_id]["weekly_seconds"] += worked
        data[user_id]["clocked_in"] = None
        data[user_id]["last_reminder_hour"] = 0
        save_data(data)

        total_seconds = data[user_id]["total_seconds"]
        weekly_seconds = data[user_id]["weekly_seconds"]

        embed = make_embed(
            "Clocked Out",
            f"{member.mention} clocked out from **Purple Haze Garage & Grill**."
        )
        embed.add_field(name="Shift Time", value=format_seconds(worked), inline=True)
        embed.add_field(name="Weekly Time", value=format_seconds(weekly_seconds), inline=True)
        embed.add_field(name="All Time", value=format_seconds(total_seconds), inline=True)
        embed.add_field(name="Time", value=f"<t:{current_unix()}:F>", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        await send_channel_embed(interaction.guild, TIMECLOCK_CHANNEL_NAME, embed)

    @discord.ui.button(label="My Hours", style=discord.ButtonStyle.primary, custom_id="timeclock_hours")
    async def my_hours_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        data = load_data()
        user_id = ensure_user(data, member)
        save_data(data)

        total_seconds, weekly_seconds = calculate_live_totals(data[user_id])

        embed = make_embed(
            "Your Hours",
            f"{member.mention}, here are your current hours."
        )
        embed.add_field(name="Weekly Time", value=format_seconds(weekly_seconds), inline=True)
        embed.add_field(name="All Time", value=format_seconds(total_seconds), inline=True)
        embed.add_field(
            name="Clock Status",
            value="Clocked In" if data[user_id]["clocked_in"] else "Clocked Out",
            inline=True
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="panel", description="Post the clock-in button panel")
async def timeclockpanel(interaction: discord.Interaction):
    if not await require_member(interaction):
        return

    member = interaction.user
    if not has_role(member, MANAGER_ROLE_NAME):
        await interaction.response.send_message(
            "You do not have the **Purple Haze Manager** role.",
            ephemeral=True
        )
        return

    # 👇 YOUR CHANNEL ID HERE
    channel = interaction.guild.get_channel(1489448597991718992)

    if channel is None:
        await interaction.response.send_message(
            "❌ Timeclock channel not found.",
            ephemeral=True
        )
        return

    embed = make_embed(
        "Purple Haze Timeclock Station",
        "Use the buttons below to clock in, clock out, or check your hours."
    )

    await channel.send(embed=embed, view=TimeclockView())

    await interaction.response.send_message(
        f"✅ Timeclock panel posted in {channel.mention}",
        ephemeral=True
    )

# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    bot.add_view(TimeclockView())

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"✅ Synced {len(synced)} guild command(s) to {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"✅ Synced {len(synced)} global command(s)")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")

    if not weekly_payroll_post.is_running():
        weekly_payroll_post.start()

    if not weekly_leaderboard_post_and_reset.is_running():
        weekly_leaderboard_post_and_reset.start()

    if not hourly_clockin_reminders.is_running():
        hourly_clockin_reminders.start()

    print(f"🟣 Purple Haze Garage Bot is online as {bot.user}")

# =========================
# CHECKS
# =========================
def interaction_in_channel(interaction: discord.Interaction, channel_name: str) -> bool:
    return interaction.channel is not None and getattr(interaction.channel, "name", None) == channel_name

async def require_channel(interaction: discord.Interaction, channel_name: str):
    if not interaction_in_channel(interaction, channel_name):
        await interaction.response.send_message(
            f"This command can only be used in **{channel_name}**.",
            ephemeral=True
        )
        return False
    return True

async def require_member(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
        return False
    return True

# =========================
# COMMANDS
# =========================
async def respond(interaction: discord.Interaction, content=None, embed=None, ephemeral=True):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)

@bot.tree.command(name="clockin", description="Clock in for your shift")
async def clockin(interaction: discord.Interaction):
    if not await require_member(interaction):
        return

    member = interaction.user

    if not has_role(member, EMPLOYEE_ROLE_NAME):
        await respond(interaction, "You do not have the **Purple Haze Employee** role.", ephemeral=True)
        return

    if is_on_loa(member):
        await respond(interaction, "You are currently marked as **LOA** and cannot clock in.", ephemeral=True)
        return

    data = load_data()
    user_id = ensure_user(data, member)

    if data[user_id]["clocked_in"] is not None:
        await respond(interaction, "⚠️ You're already clocked in.", ephemeral=True)
        return

    data[user_id]["clocked_in"] = datetime.now(timezone.utc).isoformat()
    data[user_id]["last_reminder_hour"] = 0
    save_data(data)

    embed = make_embed(
        "Clocked In",
        f"{member.mention} clocked in at **Purple Haze Garage & Grill**."
    )
    embed.add_field(name="Employee", value=member.display_name, inline=True)
    embed.add_field(name="Time", value=f"<t:{current_unix()}:F>", inline=True)

    await respond(interaction, embed=embed, ephemeral=True)
    await send_channel_embed(interaction.guild, TIMECLOCK_CHANNEL_NAME, embed)

@bot.tree.command(name="clockout", description="Clock out from your shift")
async def clockout(interaction: discord.Interaction):
    if not await require_member(interaction):
        return

    member = interaction.user

    if not has_role(member, EMPLOYEE_ROLE_NAME):
        await respond(interaction, "You do not have the **Purple Haze Employee** role.", ephemeral=True)
        return

    data = load_data()
    user_id = ensure_user(data, member)

    if data[user_id]["clocked_in"] is None:
        await respond(interaction, "⚠️ You're not clocked in.", ephemeral=True)
        return

    start = datetime.fromisoformat(data[user_id]["clocked_in"])
    end = datetime.now(timezone.utc)
    worked = int((end - start).total_seconds())

    data[user_id]["total_seconds"] += worked
    data[user_id]["weekly_seconds"] += worked
    data[user_id]["clocked_in"] = None
    data[user_id]["last_reminder_hour"] = 0
    save_data(data)

    total_seconds = data[user_id]["total_seconds"]
    weekly_seconds = data[user_id]["weekly_seconds"]

    embed = make_embed(
        "Clocked Out",
        f"{member.mention} clocked out from **Purple Haze Garage & Grill**."
    )
    embed.add_field(name="Shift Time", value=format_seconds(worked), inline=True)
    embed.add_field(name="Weekly Time", value=format_seconds(weekly_seconds), inline=True)
    embed.add_field(name="All Time", value=format_seconds(total_seconds), inline=True)
    embed.add_field(name="Time", value=f"<t:{current_unix()}:F>", inline=False)

    await respond(interaction, embed=embed, ephemeral=True)
    await send_channel_embed(interaction.guild, TIMECLOCK_CHANNEL_NAME, embed)

    payroll_role = get_member_role_name_from_list(member, PAYROLL_ROLE_NAMES)
    if payroll_role:
        weekly_pay = calculate_pay_for_role(payroll_role, weekly_seconds)
        all_time_pay = calculate_pay_for_role(payroll_role, total_seconds)
        shift_pay = calculate_pay_for_role(payroll_role, worked)

        payroll_embed = make_embed(
            "Payroll Tracking",
            f"{member.mention} has a payroll-tracked role."
        )
        payroll_embed.add_field(name="Discord Name", value=member.display_name, inline=True)
        payroll_embed.add_field(name="Role", value=payroll_role, inline=True)
        payroll_embed.add_field(name="Rate", value=f"{format_money(HOURLY_RATES.get(payroll_role, 0))}/hr", inline=True)
        payroll_embed.add_field(name="Shift Added", value=format_seconds(worked), inline=True)
        payroll_embed.add_field(name="Shift Pay", value=format_money(shift_pay), inline=True)
        payroll_embed.add_field(name="Weekly Paycheck Total", value=format_money(weekly_pay), inline=True)
        payroll_embed.add_field(name="All-Time Earnings", value=format_money(all_time_pay), inline=False)

        await send_channel_embed(interaction.guild, PAYROLL_TRACKING_CHANNEL_NAME, payroll_embed)

@bot.tree.command(name="hours", description="Check your own all-time and weekly hours")
async def hours(interaction: discord.Interaction):
    if not await require_member(interaction):
        return

    member = interaction.user
    data = load_data()
    user_id = ensure_user(data, member)
    save_data(data)

    total_seconds, weekly_seconds = calculate_live_totals(data[user_id])

    embed = make_embed(
        "Your Hours",
        f"{member.mention}, here are your current hours."
    )
    embed.add_field(name="Weekly Time", value=format_seconds(weekly_seconds), inline=True)
    embed.add_field(name="All Time", value=format_seconds(total_seconds), inline=True)
    embed.add_field(
        name="Clock Status",
        value="Clocked In" if data[user_id]["clocked_in"] else "Clocked Out",
        inline=True
    )

    await respond(interaction, embed=embed, ephemeral=True)

@bot.tree.command(name="weeklyhours", description="Check your weekly hours")
async def weeklyhours(interaction: discord.Interaction):
    if not await require_member(interaction):
        return

    member = interaction.user
    data = load_data()
    user_id = ensure_user(data, member)
    save_data(data)

    _, weekly_seconds = calculate_live_totals(data[user_id])

    embed = make_embed(
        "Weekly Hours",
        f"{member.mention}, your current weekly time is below."
    )
    embed.add_field(name="Weekly Time", value=format_seconds(weekly_seconds), inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="allhours", description="Manager view of all employee hours")
async def allhours(interaction: discord.Interaction):
    if not await require_member(interaction):
        return
    if not await require_channel(interaction, CHECKING_HOURS_CHANNEL_NAME):
        return

    member = interaction.user
    if not has_role(member, MANAGER_ROLE_NAME):
        await interaction.response.send_message(
            "You do not have the **Purple Haze Manager** role.",
            ephemeral=True
        )
        return

    data = load_data()
    text = build_allhours_text(interaction.guild, data)

    embed = make_embed("All Employee Hours", text[:4096])
    await interaction.response.send_message(embed=embed)

@app_commands.describe(
    target="Employee whose time you want to fix",
    action="add or remove",
    hours="Hours to add/remove",
    minutes="Extra minutes to add/remove",
    reason="Reason for the correction"
)
@bot.tree.command(name="fixtime", description="Manager-only: add or remove time for an employee")
async def fixtime(
    interaction: discord.Interaction,
    target: discord.Member,
    action: str,
    hours: app_commands.Range[int, 0, 999],
    minutes: app_commands.Range[int, 0, 59],
    reason: str
):
    if not await require_member(interaction):
        return
    if not await require_channel(interaction, FIXING_HOURS_CHANNEL_NAME):
        return

    manager = interaction.user
    if not has_role(manager, MANAGER_ROLE_NAME):
        await interaction.response.send_message(
            "You do not have the **Purple Haze Manager** role.",
            ephemeral=True
        )
        return

    if action.lower() not in ["add", "remove"]:
        await interaction.response.send_message(
            'Action must be either **add** or **remove**.',
            ephemeral=True
        )
        return

    data = load_data()
    user_id = ensure_user(data, target)

    delta_seconds = (hours * 3600) + (minutes * 60)

    if action.lower() == "add":
        data[user_id]["total_seconds"] += delta_seconds
        data[user_id]["weekly_seconds"] += delta_seconds
    else:
        data[user_id]["total_seconds"] = max(0, data[user_id]["total_seconds"] - delta_seconds)
        data[user_id]["weekly_seconds"] = max(0, data[user_id]["weekly_seconds"] - delta_seconds)

    save_data(data)

    total_seconds, weekly_seconds = calculate_live_totals(data[user_id])

    embed = make_embed(
        "Time Fixed",
        f"Time was updated for {target.mention}."
    )
    embed.add_field(name="Manager", value=manager.display_name, inline=True)
    embed.add_field(name="Employee", value=target.display_name, inline=True)
    embed.add_field(name="Action", value=action.title(), inline=True)
    embed.add_field(name="Amount", value=format_seconds(delta_seconds), inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="New Weekly Time", value=format_seconds(weekly_seconds), inline=True)
    embed.add_field(name="New All Time", value=format_seconds(total_seconds), inline=True)

    await interaction.response.send_message(embed=embed)

    payroll_role = get_member_role_name_from_list(target, PAYROLL_ROLE_NAMES)
    if payroll_role:
        weekly_pay = calculate_pay_for_role(payroll_role, weekly_seconds)
        all_time_pay = calculate_pay_for_role(payroll_role, total_seconds)
        adjustment_pay = calculate_pay_for_role(payroll_role, delta_seconds)

        payroll_embed = make_embed(
            "Payroll Adjustment",
            f"Payroll-tracked employee time was corrected."
        )
        payroll_embed.add_field(name="Discord Name", value=target.display_name, inline=True)
        payroll_embed.add_field(name="Role", value=payroll_role, inline=True)
        payroll_embed.add_field(name="Rate", value=f"{format_money(HOURLY_RATES.get(payroll_role, 0))}/hr", inline=True)
        payroll_embed.add_field(name="Action", value=action.title(), inline=True)
        payroll_embed.add_field(name="Adjustment", value=format_seconds(delta_seconds), inline=True)
        payroll_embed.add_field(name="Adjustment Pay", value=format_money(adjustment_pay), inline=True)
        payroll_embed.add_field(name="Reason", value=reason[:1024], inline=False)
        payroll_embed.add_field(name="Weekly Paycheck Total", value=format_money(weekly_pay), inline=True)
        payroll_embed.add_field(name="All-Time Earnings", value=format_money(all_time_pay), inline=True)

        await send_channel_embed(interaction.guild, PAYROLL_TRACKING_CHANNEL_NAME, payroll_embed)

@app_commands.describe(
    action="add or remove LOA",
    target="Employee to place on or remove from LOA",
    reason="Reason for the LOA update"
)
@bot.tree.command(name="loa", description="Manager-only: add or remove Leave of Absence")
async def loa(
    interaction: discord.Interaction,
    action: str,
    target: discord.Member,
    reason: str
):
    if not await require_member(interaction):
        return
    if not await require_channel(interaction, LEAVE_OF_ABSENCE_CHANNEL_NAME):
        return

    manager = interaction.user
    if not has_role(manager, MANAGER_ROLE_NAME):
        await interaction.response.send_message(
            "You do not have the **Purple Haze Manager** role.",
            ephemeral=True
        )
        return

    action = action.lower().strip()
    if action not in ["add", "remove"]:
        await interaction.response.send_message(
            "Action must be either **add** or **remove**.",
            ephemeral=True
        )
        return

    loa_role = discord.utils.get(interaction.guild.roles, name=LOA_ROLE_NAME)
    if not loa_role:
        await interaction.response.send_message(
            f"The **{LOA_ROLE_NAME}** role was not found. Please create it first.",
            ephemeral=True
        )
        return

    if action == "add":
        if loa_role in target.roles:
            await interaction.response.send_message(
                f"{target.mention} is already on **LOA**.",
                ephemeral=True
            )
            return

        data = load_data()
        user_id = ensure_user(data, target)

        if data[user_id]["clocked_in"] is not None:
            start = datetime.fromisoformat(data[user_id]["clocked_in"])
            end = datetime.now(timezone.utc)
            worked = int((end - start).total_seconds())

            data[user_id]["total_seconds"] += worked
            data[user_id]["weekly_seconds"] += worked
            data[user_id]["clocked_in"] = None
            data[user_id]["last_reminder_hour"] = 0
            save_data(data)

        await target.add_roles(loa_role, reason=f"LOA added by {manager} | {reason}")

        embed = make_embed(
            "Leave of Absence Updated",
            f"{target.mention} has been placed on **LOA**."
        )
        embed.add_field(name="Action", value="Add LOA", inline=True)
        embed.add_field(name="Employee", value=target.display_name, inline=True)
        embed.add_field(name="Manager", value=manager.display_name, inline=True)
        embed.add_field(name="Reason", value=reason[:1024], inline=False)

        await interaction.response.send_message(embed=embed)
        return

    if action == "remove":
        if loa_role not in target.roles:
            await interaction.response.send_message(
                f"{target.mention} is not currently on **LOA**.",
                ephemeral=True
            )
            return

        await target.remove_roles(loa_role, reason=f"LOA removed by {manager} | {reason}")

        embed = make_embed(
            "Leave of Absence Updated",
            f"{target.mention} has been removed from **LOA**."
        )
        embed.add_field(name="Action", value="Remove LOA", inline=True)
        embed.add_field(name="Employee", value=target.display_name, inline=True)
        embed.add_field(name="Manager", value=manager.display_name, inline=True)
        embed.add_field(name="Reason", value=reason[:1024], inline=False)

        await interaction.response.send_message(embed=embed)

@loa.autocomplete("action")
async def loa_action_autocomplete(interaction: discord.Interaction, current: str):
    actions = ["add", "remove"]
    return [
        app_commands.Choice(name=a, value=a)
        for a in actions if current.lower() in a.lower()
    ]

@bot.tree.command(name="leaderboard", description="Post the Purple Haze leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if not await require_member(interaction):
        return
    if not await require_channel(interaction, LEADERBOARD_CHANNEL_NAME):
        return

    data = load_data()
    embeds = build_leaderboard_embeds(interaction.guild, data)

    await interaction.response.send_message("Posting leaderboard...", ephemeral=True)
    for embed in embeds:
        await interaction.channel.send(embed=embed)

@bot.tree.command(name="payroll", description="Post the current weekly payroll summary")
async def payroll(interaction: discord.Interaction):
    if not await require_member(interaction):
        return
    if not await require_channel(interaction, PAYROLL_TRACKING_CHANNEL_NAME):
        return

    data = load_data()
    embeds = build_payroll_summary_embeds(interaction.guild, data)

    await interaction.response.send_message("Posting payroll summary...", ephemeral=True)
    for embed in embeds:
        await interaction.channel.send(embed=embed)

@fixtime.autocomplete("action")
async def fixtime_action_autocomplete(interaction: discord.Interaction, current: str):
    actions = ["add", "remove"]
    return [
        app_commands.Choice(name=a, value=a)
        for a in actions if current.lower() in a.lower()
    ]

bot.run(TOKEN)
