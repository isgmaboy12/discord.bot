import discord
from discord.ext import commands
import sqlite3
from keep_alive import keep_alive

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Database setup
conn = sqlite3.connect("teams_and_fines.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS fines (
    user_id INTEGER PRIMARY KEY,
    amount INTEGER DEFAULT 0
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS rosters (
    user_id INTEGER PRIMARY KEY,
    team_name TEXT,
    manager_id INTEGER,
    contract_duration INTEGER
)
""")
conn.commit()

TEAM_ROLES = {
    1323533878220165153: "Newcastle United",
    1323533787795292242: "Atletico Madrid",
    1323533531028263035: "Napoli FC",
    1323533418386034700: "Manchester City",
    1323533348093820979: "Manchester United",
    1323533263356297329: "Tottenham Hotspurs",
    1323533125619548180: "Paris-Saint-Germain",
    1323533030064656424: "Borussia Dortmund",
    1323532901710565376: "FC Barcelona",
    1323532650085875824: "Real Madrid CF",
}

FINE_CHANNEL_ID = 1323371489465995264
ANNOUNCE_CHANNEL_ID = 1323198905374212159


def get_manager_team(ctx):
    for role_id, team_name in TEAM_ROLES.items():
        if discord.utils.get(ctx.author.roles, id=role_id):
            return team_name
    return None


@bot.event
async def on_ready():
    print(f"Bot is ready. Logged in as {bot.user}.")
# Call keep_alive() before running the bot to keep it alive
keep_alive()

@bot.command()
async def fine(ctx, member: discord.Member, amount: int, *, reason: str = "No reason provided"):
    c.execute("INSERT INTO fines (user_id, amount) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?", 
              (member.id, amount, amount))
    conn.commit()

    embed = discord.Embed(
        title="🚨 Fine Issued",
        description=f"**User:** {member.mention}\n**Amount:** `${amount}`\n**Reason:** {reason}\n**Issued by:** {ctx.author.mention}",
        color=discord.Color.red()
    )

    channel = bot.get_channel(FINE_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)


@bot.command()
async def bail(ctx, member: discord.Member, amount: int):
    c.execute("SELECT amount FROM fines WHERE user_id = ?", (member.id,))
    result = c.fetchone()
    fine_amount = result[0] if result else 0

    if fine_amount == 0:
        await ctx.send(f"ℹ️ {member.mention} has no fines recorded.")
        return

    new_fine = max(0, fine_amount - amount)
    c.execute("UPDATE fines SET amount = ? WHERE user_id = ?", (new_fine, member.id))
    conn.commit()

    embed = discord.Embed(
        title="🟦 Bail Processed",
        description=f"**User:** {member.mention}\n**Bail Amount:** `${amount}`\n**Remaining Fine:** `${new_fine}`\n**Processed by:** {ctx.author.mention}",
        color=discord.Color.blue()
    )

    channel = bot.get_channel(FINE_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)


@bot.command()
async def teams(ctx):
    c.execute("SELECT DISTINCT team_name FROM rosters")
    teams = [row[0] for row in c.fetchall()]
    if not teams:
        await ctx.send("ℹ️ No teams have players signed yet.")
        return

    class TeamView(discord.ui.View):
        def __init__(self):
            super().__init__()

            for team_name in teams:
                button = discord.ui.Button(label=team_name, style=discord.ButtonStyle.primary)
                button.callback = self.create_callback(team_name)
                self.add_item(button)

        def create_callback(self, team_name):
            async def callback(interaction: discord.Interaction):
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(view=self)

                c.execute("SELECT user_id FROM rosters WHERE team_name = ?", (team_name,))
                players = [f"<@{row[0]}>" for row in c.fetchall()]
                player_list = "\n".join(players) if players else "No players signed."

                c.execute("SELECT manager_id FROM rosters WHERE team_name = ? LIMIT 1", (team_name,))
                manager = c.fetchone()
                manager_text = f"<@{manager[0]}>" if manager else "Unknown"

                embed = discord.Embed(title=f"📋 {team_name} Roster", color=discord.Color.gold())
                embed.add_field(name="Manager", value=manager_text, inline=False)
                embed.add_field(name="Players", value=player_list, inline=False)

                await interaction.response.send_message(embed=embed, ephemeral=True)

            return callback

    await ctx.send("Select a team to view its roster:", view=TeamView())


@bot.command()
async def profile(ctx):
    user = ctx.author

    c.execute("SELECT amount FROM fines WHERE user_id = ?", (user.id,))
    fine_result = c.fetchone()
    fine_amount = fine_result[0] if fine_result else 0
    fines_text = f"${fine_amount}" if fine_amount > 0 else "None"

    user_team = None
    for role_id, team_name in TEAM_ROLES.items():
        if discord.utils.get(user.roles, id=role_id):
            user_team = team_name
            break

    free_agent = "No" if user_team else "Yes"
    team_display = user_team if user_team else "None"

    embed = discord.Embed(title="📂 User Profile", color=discord.Color.dark_gray())
    embed.set_thumbnail(url=user.avatar.url)
    embed.add_field(name="**Username**", value=user.name, inline=True)
    embed.add_field(name="**User ID**", value=user.id, inline=True)
    embed.add_field(name="**Fines (Unpaid)**", value=fines_text, inline=False)
    embed.add_field(name="**Team**", value=team_display, inline=True)
    embed.add_field(name="**Free Agent**", value=free_agent, inline=True)

    await ctx.send(embed=embed)


@bot.command()
async def sign(ctx, member: discord.Member, seasons: int):
    if seasons < 1 or seasons > 4:
        await ctx.send("❌ Seasons must be between 1 and 4.")
        return

    if not ctx.message.attachments:
        await ctx.send("❌ Please provide proof as an image attachment.")
        return

    proof = ctx.message.attachments[0].url
    team_name = get_manager_team(ctx)

    if not team_name:
        await ctx.send("❌ You do not have a valid team role to use this command.")
        return

    c.execute("INSERT INTO rosters (user_id, team_name, manager_id, contract_duration) VALUES (?, ?, ?, ?)", 
              (member.id, team_name, ctx.author.id, seasons))
    conn.commit()

    embed = discord.Embed(
        title="✅ Player Signed!",
        description=f"**{member.mention}** has joined **{team_name}** for **{seasons} season(s)**.\n📎 [View Proof]({proof})",
        color=discord.Color.green()
    )

    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)


@bot.command()
async def release(ctx, member: discord.Member):
    manager_team = get_manager_team(ctx)
    if not manager_team:
        await ctx.send("❌ You are not a team manager.")
        return

    c.execute("DELETE FROM rosters WHERE user_id = ?", (member.id,))
    conn.commit()

    embed = discord.Embed(
        title="⚠️ Player Released",
        description=f"**{member.mention}** has been released from **{manager_team}**.",
        color=discord.Color.orange()
    )

    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)

# Run the bot (Replace 'YOUR_BOT_TOKEN' with your actual token)
import os
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
