"""
ESPN Fantasy Basketball Data Puller
Connects to a private ESPN fantasy basketball league and displays:
  - League standings
  - Weekly scoreboard
  - Team rosters with player stats
  - Detailed matchup analysis with projections
"""

import os
import sys
from dotenv import load_dotenv
import espn_api.requests.constant as espn_constant
espn_constant.FANTASY_BASE_ENDPOINT = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/'
from espn_api.basketball import League
from tabulate import tabulate

load_dotenv()

MY_TEAM_KEYWORD = "brooklyn pet shop"

# ESPN stat numeric-string ID -> display label (in display order)
STAT_DISPLAY = [
    ('0',  'PTS'),
    ('6',  'REB'),
    ('3',  'AST'),
    ('2',  'STL'),
    ('1',  'BLK'),
    ('11', 'TO'),
    ('17', '3PM'),
]

# Percentage categories: (label, makes_id, attempts_id)
PCT_STATS = [
    ('FG%', '13', '14'),
    ('FT%', '15', '16'),
]

# Human-readable keys some espn_api versions use -> numeric string ID
_HR_TO_ID = {
    'PTS': '0', 'BLK': '1', 'STL': '2', 'AST': '3', 'REB': '6',
    'TO': '11', 'FGM': '13', 'FGA': '14', 'FTM': '15', 'FTA': '16', '3PM': '17',
}


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
        if hasattr(matchup, 'home_score'):
            home_score = round(matchup.home_score, 1) if matchup.home_score else 0.0
            away_score = round(matchup.away_score, 1) if matchup.away_score else 0.0
            score_str = f"{home_score} - {away_score}"
        elif hasattr(matchup, 'home_wins'):
            score_str = f"{matchup.home_wins}-{matchup.home_losses}-{matchup.home_ties} vs {matchup.away_wins}-{matchup.away_losses}-{matchup.away_ties}"
        else:
            score_str = "In progress"
        rows.append([home.team_name, score_str, away.team_name])

    print(tabulate(
        rows,
        headers=["Home Team", "Score (W-L-T)", "Away Team"],
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


# ── Matchup analysis helpers ───────────────────────────────────────────────

def _normalize_stats(raw_stats: dict) -> dict:
    """Normalize a player.stats dict to string numeric-ID keys."""
    out = {}
    for k, v in (raw_stats or {}).items():
        if v is None:
            continue
        sk = str(k)
        # convert human-readable keys to numeric string IDs
        sk = _HR_TO_ID.get(sk, sk)
        try:
            out[sk] = out.get(sk, 0) + float(v)
        except (TypeError, ValueError):
            pass
    return out


def _sum_lineup_stats(lineup) -> dict:
    """Sum normalized stats from all non-IR players in a lineup."""
    totals = {}
    for player in lineup:
        if player.slot_position == 'IR':
            continue
        for k, v in _normalize_stats(player.stats).items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _pct(totals: dict, makes_id: str, att_id: str) -> float:
    m = totals.get(makes_id, 0)
    a = totals.get(att_id, 0)
    return round(m / a * 100, 1) if a else 0.0


def _get_remaining_games(league: League) -> dict:
    """Return {proTeamId: games_remaining_this_week}."""
    current_period = league.scoringPeriodId

    # Try to find the last scoring period of the current matchup week
    end_period = current_period + 6  # safe fallback
    try:
        periods = league.settings.matchup_periods.get(league.currentMatchupPeriod, [])
        if periods:
            end_period = max(periods)
    except Exception:
        pass

    try:
        data = league.espn_request.get_pro_schedule()
    except Exception:
        return {}

    pro_teams = (data.get('settings') or {}).get('proTeams', [])
    remaining = {}
    for team in pro_teams:
        tid = team.get('id')
        if tid is None:
            continue
        count = 0
        for period_str, games in team.get('proGamesByScoringPeriod', {}).items():
            try:
                period = int(period_str)
            except ValueError:
                continue
            if current_period <= period <= end_period:
                count += len(games)
        remaining[tid] = count
    return remaining


def _get_last15_stats(league: League, player_ids: list) -> dict:
    """Return {playerId: {stat_id_str: per_game_avg}} from last-15-days data.
    Falls back to season averages if last-15 is unavailable."""
    if not player_ids:
        return {}
    try:
        data = league.espn_request.get_player_card(
            playerIds=player_ids,
            max_scoring_period=league.scoringPeriodId,
            additional_filters=['022025'],  # last 15 days
        )
    except Exception:
        return {}

    result = {}
    for entry in (data.get('players') or []):
        pid = entry.get('id')
        if pid is None:
            continue
        player_data = (entry.get('playerPoolEntry') or {}).get('player') or {}
        chosen = {}
        fallback = {}
        for stat_entry in (player_data.get('stats') or []):
            ext_id = stat_entry.get('externalId', '')
            # averageStats gives per-game averages for the period
            avg = stat_entry.get('averageStats') or stat_entry.get('stats') or {}
            if ext_id == '022025' and not chosen:
                chosen = avg
            elif ext_id == '002025' and not fallback:
                fallback = avg
        raw = chosen or fallback
        result[pid] = {str(k): float(v) for k, v in raw.items() if v is not None}
    return result


def show_my_matchup(league: League) -> None:
    print("\n" + "=" * 72)
    print("  MY MATCHUP ANALYSIS — Brooklyn Pet Shop")
    print("=" * 72)

    # Find my team
    my_team = next(
        (t for t in league.teams if MY_TEAM_KEYWORD in t.team_name.lower()), None
    )
    if not my_team:
        print(f"  Team '{MY_TEAM_KEYWORD}' not found in league.")
        return

    # Find my box score
    try:
        box_scores = league.box_scores()
    except Exception as e:
        print(f"  Could not load box scores: {e}")
        return

    my_bs = None
    i_am_home = False
    for bs in box_scores:
        if bs.home_team.team_id == my_team.team_id:
            my_bs, i_am_home = bs, True
            break
        elif bs.away_team.team_id == my_team.team_id:
            my_bs, i_am_home = bs, False
            break

    if not my_bs:
        print("  No active matchup found this week.")
        return

    my_lineup  = my_bs.home_lineup if i_am_home else my_bs.away_lineup
    opp_lineup = my_bs.away_lineup if i_am_home else my_bs.home_lineup
    opp_team   = my_bs.away_team   if i_am_home else my_bs.home_team

    # ── DEBUG: print raw data to understand structure ─────────────────────
    if my_lineup:
        p = my_lineup[0]
        print(f"\n  [DEBUG] First player: {p.name}")
        print(f"  [DEBUG] slot_position: {p.slot_position}")
        print(f"  [DEBUG] proTeam: {getattr(p, 'proTeam', 'N/A')}")
        print(f"  [DEBUG] stats keys (first 10): {list((p.stats or {}).keys())[:10]}")
        print(f"  [DEBUG] stats sample: {dict(list((p.stats or {}).items())[:5])}")
        print(f"  [DEBUG] all attributes: {[a for a in dir(p) if not a.startswith('_')]}")

    try:
        sched_data = league.espn_request.get_pro_schedule()
        settings = sched_data.get('settings', {})
        print(f"\n  [DEBUG] pro schedule top-level keys: {list(sched_data.keys())}")
        print(f"  [DEBUG] settings keys: {list(settings.keys())[:10]}")
        pro_teams = settings.get('proTeams', [])
        if pro_teams:
            t0 = pro_teams[0]
            print(f"  [DEBUG] first proTeam keys: {list(t0.keys())}")
            pbsp = t0.get('proGamesByScoringPeriod', {})
            print(f"  [DEBUG] proGamesByScoringPeriod sample keys: {list(pbsp.keys())[:5]}")
            print(f"  [DEBUG] current scoringPeriodId: {league.scoringPeriodId}")
    except Exception as ex:
        print(f"  [DEBUG] pro schedule error: {ex}")

    input("\n  [DEBUG] Press Enter to continue...")
    # ── END DEBUG ─────────────────────────────────────────────────────────

    # ── SECTION 1: Current Category Scores ───────────────────────────────
    print(f"\n  Opponent: {opp_team.team_name}")
    print(f"\n  {'─' * 68}")
    print("  SECTION 1 — CURRENT CATEGORY SCORES")
    print(f"  {'─' * 68}")

    my_tot  = _sum_lineup_stats(my_lineup)
    opp_tot = _sum_lineup_stats(opp_lineup)

    rows = []
    for sid, name in STAT_DISPLAY:
        mv = my_tot.get(sid, 0)
        ov = opp_tot.get(sid, 0)
        if sid == '11':  # turnovers: lower is better
            res = 'W' if mv < ov else ('L' if mv > ov else 'T')
        else:
            res = 'W' if mv > ov else ('L' if mv < ov else 'T')
        rows.append([name, round(mv, 1), round(ov, 1), res])

    for label, mid, aid in PCT_STATS:
        mp = _pct(my_tot, mid, aid)
        op = _pct(opp_tot, mid, aid)
        res = 'W' if mp > op else ('L' if mp < op else 'T')
        rows.append([label, mp, op, res])

    me_col  = my_team.team_name[:20]
    opp_col = opp_team.team_name[:20]
    print(tabulate(
        rows,
        headers=["Cat", me_col, opp_col, ""],
        tablefmt="simple",
        colalign=("left", "right", "right", "center"),
    ))

    w = sum(1 for r in rows if r[3] == 'W')
    l = sum(1 for r in rows if r[3] == 'L')
    t = sum(1 for r in rows if r[3] == 'T')
    print(f"\n  Current standing: {w}W - {l}L - {t}T")

    # ── SECTION 2: Player Projections ─────────────────────────────────────
    print(f"\n  {'─' * 68}")
    print("  SECTION 2 — EXPECTED REMAINING STATS  (last-15d avg/g × games left)")
    print(f"  {'─' * 68}")

    active   = [p for p in my_lineup if p.slot_position != 'IR']
    pid_list = [p.playerId for p in active]

    print("  Fetching remaining games and last-15-day stats...")
    rem_games = _get_remaining_games(league)
    last15    = _get_last15_stats(league, pid_list)

    # Build reverse map: proTeam abbreviation -> ESPN pro team numeric ID
    try:
        from espn_api.basketball.constant import PRO_TEAM_MAP
        abbr_to_id = {v: k for k, v in PRO_TEAM_MAP.items()}
    except Exception:
        abbr_to_id = {}

    proj_totals = {}
    cat_labels  = [name for _, name in STAT_DISPLAY] + ['FG%', 'FT%']
    p_rows = []

    for player in active:
        pro_team_abbr = getattr(player, 'proTeam', None)
        pro_id        = abbr_to_id.get(pro_team_abbr) if pro_team_abbr else None
        games_left    = rem_games.get(pro_id, 0) if pro_id is not None else 0

        s15 = last15.get(player.playerId, {})

        cells = []
        for sid, _ in STAT_DISPLAY:
            pg   = float(s15.get(sid, 0) or 0)
            proj = pg * games_left
            proj_totals[sid] = proj_totals.get(sid, 0) + proj
            cells.append(f"{pg:.1f}×{games_left}={proj:.1f}")

        # accumulate makes/attempts for FG% and FT%
        for mid, aid in [('13', '14'), ('15', '16')]:
            m_pg = float(s15.get(mid, 0) or 0)
            a_pg = float(s15.get(aid, 0) or 0)
            proj_totals[mid] = proj_totals.get(mid, 0) + m_pg * games_left
            proj_totals[aid] = proj_totals.get(aid, 0) + a_pg * games_left

        fg_pct = _pct({'13': float(s15.get('13', 0) or 0), '14': float(s15.get('14', 0) or 0)}, '13', '14')
        ft_pct = _pct({'15': float(s15.get('15', 0) or 0), '16': float(s15.get('16', 0) or 0)}, '15', '16')
        cells += [f"{fg_pct:.1f}%", f"{ft_pct:.1f}%"]

        p_rows.append([player.name[:24], player.slot_position, games_left] + cells)

    print(tabulate(
        p_rows,
        headers=["Player", "Slot", "G"] + cat_labels,
        tablefmt="simple",
    ))

    # ── SECTION 3: Projected End-of-Week Totals ───────────────────────────
    print(f"\n  {'─' * 68}")
    print("  SECTION 3 — PROJECTED END-OF-WEEK TOTALS (current + remaining)")
    print(f"  {'─' * 68}")

    final_rows = []
    for sid, name in STAT_DISPLAY:
        cur  = my_tot.get(sid, 0)
        proj = proj_totals.get(sid, 0)
        final_rows.append([name, round(cur, 1), round(proj, 1), round(cur + proj, 1)])

    for label, mid, aid in PCT_STATS:
        c_m = my_tot.get(mid, 0);       c_a = my_tot.get(aid, 0)
        p_m = proj_totals.get(mid, 0);  p_a = proj_totals.get(aid, 0)
        cur_pct  = round(c_m / c_a * 100, 1) if c_a else 0.0
        proj_pct = round(p_m / p_a * 100, 1) if p_a else 0.0
        comb_pct = round((c_m + p_m) / (c_a + p_a) * 100, 1) if (c_a + p_a) else 0.0
        final_rows.append([label, cur_pct, proj_pct, comb_pct])

    print(tabulate(
        final_rows,
        headers=["Category", "Current", "Proj Remaining", "Combined"],
        tablefmt="simple",
        colalign=("left", "right", "right", "right"),
    ))


# ── Menu ──────────────────────────────────────────────────────────────────

def print_menu() -> None:
    print("\n" + "=" * 60)
    print("  ESPN FANTASY BASKETBALL")
    print("=" * 60)
    print("  1. Standings")
    print("  2. Scoreboard (current week)")
    print("  3. All team rosters & player stats")
    print("  4. Roster for a specific team")
    print("  5. Show everything")
    print("  6. My matchup analysis (Brooklyn Pet Shop)")
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
        elif choice == "6":
            show_my_matchup(league)
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid option, please try again.")


if __name__ == "__main__":
    main()
