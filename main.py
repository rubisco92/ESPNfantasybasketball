"""
ESPN Fantasy Basketball Data Puller
Connects to a private ESPN fantasy basketball league and displays:
  - League standings
  - Weekly scoreboard
  - Team rosters with player stats
"""

import os
import sys
from dotenv import load_dotenv
import espn_api.requests.constant as espn_constant
espn_constant.FANTASY_BASE_ENDPOINT = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/'
from espn_api.basketball import League
from tabulate import tabulate

load_dotenv()


def get_league() -> League:
    league_id = os.getenv("LEAGUE_ID")
    season_year = os.getenv("SEASON_YEAR")
    espn_s2 = os.getenv("ESPN_S2")
    swid = os.getenv("SWID")

    missing = [k for k, v in {
        "LEAGUE_ID": league_id,
        "SEASON_YEAR": season_year,
        "ESPN_S2": espn_s2,
        "SWID": swid,
    }.items() if not v]

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    return League(
        league_id=int(league_id),
        year=int(season_year),
        espn_s2=espn_s2,
        swid=swid,
    )


def show_standings(league: League) -> None:
    print("\n" + "=" * 60)
    print("  LEAGUE STANDINGS")
    print("=" * 60)

    rows = []
    # Sort teams by wins descending, then losses ascending
    sorted_teams = sorted(league.teams, key=lambda t: (-t.wins, t.losses))

    for rank, team in enumerate(sorted_teams, start=1):
        rows.append([
            rank,
            team.team_name,
            team.owner,
            team.wins,
            team.losses,
            round(team.points_for, 1),
            round(team.points_against, 1),
        ])

    print(tabulate(
        rows,
        headers=["Rank", "Team", "Owner", "W", "L", "PF", "PA"],
        tablefmt="simple",
    ))


def show_scoreboard(league: League) -> None:
    print("\n" + "=" * 60)
    print("  CURRENT WEEK SCOREBOARD")
    print("=" * 60)

    try:
        box_scores = league.box_scores()
    except Exception as e:
        print(f"  Could not load scoreboard: {e}")
        return

    rows = []
    for matchup in box_scores:
        home = matchup.home_team
        away = matchup.away_team
        home_score = round(matchup.home_score, 1) if matchup.home_score else 0.0
        away_score = round(matchup.away_score, 1) if matchup.away_score else 0.0
        rows.append([
            home.team_name,
            home_score,
            "vs",
            away_score,
            away.team_name,
        ])

    print(tabulate(
        rows,
        headers=["Home Team", "Home Pts", "", "Away Pts", "Away Team"],
        tablefmt="simple",
    ))


def show_roster(team, league: League) -> None:
    print(f"\n  Roster: {team.team_name} ({team.owner})")
    print("  " + "-" * 56)

    rows = []
    for player in team.roster:
        avg_pts = getattr(player, "avg_points", None)
        total_pts = getattr(player, "total_points", None)
        position = getattr(player, "position", "N/A")
        injured = " (INJ)" if getattr(player, "injured", False) else ""

        rows.append([
            player.name + injured,
            position,
            round(avg_pts, 1) if avg_pts is not None else "N/A",
            round(total_pts, 1) if total_pts is not None else "N/A",
        ])

    print(tabulate(
        rows,
        headers=["Player", "Pos", "Avg Pts", "Total Pts"],
        tablefmt="simple",
        colalign=("left", "center", "right", "right"),
    ))


def show_all_rosters(league: League) -> None:
    print("\n" + "=" * 60)
    print("  TEAM ROSTERS & PLAYER STATS")
    print("=" * 60)

    for team in league.teams:
        show_roster(team, league)


def print_menu() -> None:
    print("\n" + "=" * 60)
    print("  ESPN FANTASY BASKETBALL")
    print("=" * 60)
    print("  1. Standings")
    print("  2. Scoreboard (current week)")
    print("  3. All team rosters & player stats")
    print("  4. Roster for a specific team")
    print("  5. Show everything")
    print("  0. Exit")
    print("=" * 60)


def main() -> None:
    print("Connecting to ESPN Fantasy Basketball league...")
    league = get_league()
    print(f"Connected: {league.settings.name} ({league.year})")

    while True:
        print_menu()
        choice = input("Select an option: ").strip()

        if choice == "1":
            show_standings(league)
        elif choice == "2":
            show_scoreboard(league)
        elif choice == "3":
            show_all_rosters(league)
        elif choice == "4":
            print("\nAvailable teams:")
            for i, team in enumerate(league.teams, start=1):
                print(f"  {i}. {team.team_name} ({team.owner})")
            pick = input("Enter team number: ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(league.teams):
                show_roster(league.teams[int(pick) - 1], league)
            else:
                print("Invalid selection.")
        elif choice == "5":
            show_standings(league)
            show_scoreboard(league)
            show_all_rosters(league)
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid option, please try again.")


if __name__ == "__main__":
    main()
