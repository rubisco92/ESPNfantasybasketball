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
from espn_api.basketball.constant import PRO_TEAM_MAP
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

# Percentage categories
PCT_LABELS = ['FG%', 'FT%']

# Result string mapping from ESPN API
_RESULT_MAP = {'WIN': 'W', 'LOSS': 'L', 'TIE': 'T', 'W': 'W', 'L': 'L', 'T': 'T'}


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


def _get_current_matchup_period(league: League) -> int:
    """Return the actual current matchup period by scanning the schedule for
    undecided matchups.  Falls back to league.currentMatchupPeriod."""
    # Cache result so we only make the API call once per session
    cached = getattr(league, '_current_mp_cache', None)
    if cached is not None:
        return cached

    # matchup_ids is populated for H2H points leagues; may be empty for H2H category
    if league.matchup_ids:
        sp = str(league.scoringPeriodId)
        for mp, periods in league.matchup_ids.items():
            if sp in [str(p) for p in periods]:
                league._current_mp_cache = mp
                return mp

    # For H2H category leagues: fetch the schedule and find undecided matchups
    try:
        data = league.espn_request.league_get(params={'view': 'mMatchup'})
        schedule = data.get('schedule', [])
        undecided = {
            m['matchupPeriodId'] for m in schedule
            if m.get('winner') == 'UNDECIDED' and 'matchupPeriodId' in m
        }
        if undecided:
            mp = min(undecided)
            league._current_mp_cache = mp
            return mp
    except Exception:
        pass

    mp = league.currentMatchupPeriod
    league._current_mp_cache = mp
    return mp


def _box_scores_for_current_week(league: League):
    """Return box scores for the actual current week."""
    current_mp = _get_current_matchup_period(league)
    return league.box_scores(
        matchup_period=current_mp,
        scoring_period=league.scoringPeriodId,
    )


def show_scoreboard(league: League) -> None:
    print("\n" + "=" * 60)
    print("  CURRENT WEEK SCOREBOARD")
    print("=" * 60)

    try:
        box_scores = _box_scores_for_current_week(league)
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
            score_str = (
                f"{matchup.home_wins}-{matchup.home_losses}-{matchup.home_ties}"
                f" vs "
                f"{matchup.away_wins}-{matchup.away_losses}-{matchup.away_ties}"
            )
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

def _pct(makes: float, attempts: float) -> float:
    return round(makes / attempts * 100, 1) if attempts else 0.0


def _get_pro_schedule(league: League) -> dict:
    """Return {proTeamId: {period_str: [games]}} — cached on the league object."""
    cached = getattr(league, '_pro_sched_cache', None)
    if cached is not None:
        return cached
    # Newer espn_api versions expose league.pro_schedule; older ones don't
    if hasattr(league, 'pro_schedule'):
        league._pro_sched_cache = league.pro_schedule
        return league.pro_schedule
    raw = league.espn_request.get_pro_schedule()
    sched = {
        t['id']: t.get('proGamesByScoringPeriod', {})
        for t in raw.get('settings', {}).get('proTeams', [])
    }
    league._pro_sched_cache = sched
    return sched


def _get_remaining_games(league: League) -> dict:
    """Return {proTeamId: games_remaining_this_matchup_week}."""
    current_period = league.scoringPeriodId

    # Determine the last scoring period of the current matchup week
    end_period = current_period + 6  # safe fallback (~1 week of daily periods)
    try:
        if league.matchup_ids:
            current_mp = _get_current_matchup_period(league)
            periods = league.matchup_ids.get(current_mp, [])
            if periods:
                end_period = max(int(p) for p in periods)
        else:
            # H2H category: try settings.matchup_periods
            mp_map = getattr(league.settings, 'matchup_periods', {})
            if mp_map:
                periods = mp_map.get(_get_current_matchup_period(league), [])
                if periods:
                    end_period = max(int(p) for p in periods)
    except Exception:
        pass

    pro_sched = _get_pro_schedule(league)
    remaining = {}
    for pro_id, schedule in pro_sched.items():
        if pro_id == 0:
            continue
        count = 0
        for period_str, games in schedule.items():
            try:
                period = int(period_str)
            except (ValueError, TypeError):
                continue
            if current_period <= period <= end_period:
                count += len(games)
        remaining[pro_id] = count
    return remaining


def _get_last15_stats(league: League, player_ids: list) -> dict:
    """Return {playerId: {stat_id_str: per_game_avg}} from last-15-days data.
    Falls back to season averages if last-15 is unavailable.
    Stats keys are numeric strings ('0'=PTS, '6'=REB, '13'=FGM, etc.)."""
    if not player_ids:
        return {}

    last15_id = f'02{league.year}'   # e.g. '022026' for 2025-26 season
    season_id  = f'00{league.year}'  # e.g. '002026'

    try:
        data = league.espn_request.get_player_card(
            playerIds=player_ids,
            max_scoring_period=league.scoringPeriodId,
            additional_filters=[last15_id],
        )
    except Exception:
        return {}

    result = {}
    for entry in (data.get('players') or []):
        pid = entry.get('id')
        if pid is None:
            continue
        player_data = (entry.get('playerPoolEntry') or {}).get('player') or {}
        chosen   = {}
        fallback = {}
        for split in (player_data.get('stats') or []):
            split_id = split.get('id', '')
            # averageStats holds per-game averages with numeric-string keys
            avg = split.get('averageStats') or split.get('stats') or {}
            if split_id == last15_id and not chosen:
                chosen = avg
            elif split_id == season_id and not fallback:
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

    # Find my box score for the current week
    try:
        box_scores = _box_scores_for_current_week(league)
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

    opp_team = my_bs.away_team if i_am_home else my_bs.home_team

    # ── SECTION 1: Current Category Scores ───────────────────────────────
    # H2HCategoryBoxScore provides home_stats / away_stats dicts:
    #   { 'PTS': {'value': 103.2, 'result': 'WIN'}, 'REB': {...}, ... }
    # These are the cumulative category totals ESPN has already computed.
    my_stats  = my_bs.home_stats  if i_am_home else my_bs.away_stats
    opp_stats = my_bs.away_stats  if i_am_home else my_bs.home_stats

    print(f"\n  Opponent: {opp_team.team_name}")
    print(f"\n  {'─' * 68}")
    print("  SECTION 1 — CURRENT CATEGORY SCORES")
    print(f"  {'─' * 68}")

    rows = []
    for _, label in STAT_DISPLAY:
        my_d  = my_stats.get(label,  {})
        opp_d = opp_stats.get(label, {})
        my_v  = float(my_d.get('value',  0) or 0)
        opp_v = float(opp_d.get('value', 0) or 0)
        raw_r = my_d.get('result', 'TIE')
        res   = _RESULT_MAP.get(str(raw_r).upper(), 'T')
        rows.append([label, round(my_v, 1), round(opp_v, 1), res])

    for label in PCT_LABELS:
        my_d  = my_stats.get(label,  {})
        opp_d = opp_stats.get(label, {})
        my_v  = float(my_d.get('value',  0) or 0)
        opp_v = float(opp_d.get('value', 0) or 0)
        # ESPN may store as decimal (0.481) or percentage (48.1)
        if 0 < my_v  <= 1.0: my_v  *= 100
        if 0 < opp_v <= 1.0: opp_v *= 100
        raw_r = my_d.get('result', 'TIE')
        res   = _RESULT_MAP.get(str(raw_r).upper(), 'T')
        rows.append([label, f"{round(my_v, 1)}%", f"{round(opp_v, 1)}%", res])

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
    # Use my_team.roster for the full 13-player roster (not the box score
    # lineup which may only show 9 active-slot players with wrong slots).
    # player.lineupSlot is set from team roster data (PG/SG/BE/IR/etc.)
    print(f"\n  {'─' * 68}")
    print("  SECTION 2 — EXPECTED REMAINING STATS  (last-15d avg/g × games left)")
    print(f"  {'─' * 68}")

    all_players = my_team.roster           # all 13 players
    active      = [p for p in all_players if p.lineupSlot != 'IR']
    pid_list    = [p.playerId for p in active]

    print("  Fetching remaining games and last-15-day stats...")
    rem_games = _get_remaining_games(league)
    last15    = _get_last15_stats(league, pid_list)

    # Build reverse map: abbreviation → ESPN pro team ID
    abbr_to_id = {v: k for k, v in PRO_TEAM_MAP.items()}

    proj_totals = {}
    cat_labels  = [lbl for _, lbl in STAT_DISPLAY] + PCT_LABELS
    p_rows      = []

    for player in active:
        pro_id     = abbr_to_id.get(player.proTeam)
        games_left = rem_games.get(pro_id, 0) if pro_id is not None else 0
        s15        = last15.get(player.playerId, {})
        slot       = player.lineupSlot or player.position or '?'

        cells = []
        for sid, _ in STAT_DISPLAY:
            pg   = float(s15.get(sid, 0) or 0)
            proj = pg * games_left
            proj_totals[sid] = proj_totals.get(sid, 0) + proj
            cells.append(f"{pg:.1f}×{games_left}={proj:.1f}")

        # Accumulate makes/attempts for FG% and FT%
        for mid, aid in [('13', '14'), ('15', '16')]:
            m_pg = float(s15.get(mid, 0) or 0)
            a_pg = float(s15.get(aid, 0) or 0)
            proj_totals[mid] = proj_totals.get(mid, 0) + m_pg * games_left
            proj_totals[aid] = proj_totals.get(aid, 0) + a_pg * games_left

        fg_pct = _pct(float(s15.get('13', 0) or 0), float(s15.get('14', 0) or 0))
        ft_pct = _pct(float(s15.get('15', 0) or 0), float(s15.get('16', 0) or 0))
        cells += [f"{fg_pct:.1f}%", f"{ft_pct:.1f}%"]

        p_rows.append([player.name[:24], slot, games_left] + cells)

    print(tabulate(
        p_rows,
        headers=["Player", "Slot", "G"] + cat_labels,
        tablefmt="simple",
    ))

    # ── SECTION 3: Projected End-of-Week Totals ───────────────────────────
    print(f"\n  {'─' * 68}")
    print("  SECTION 3 — PROJECTED END-OF-WEEK TOTALS (current + remaining)")
    print(f"  {'─' * 68}")

    # Current totals from Section 1 stats
    my_raw = {lbl: float((my_stats.get(lbl) or {}).get('value', 0) or 0)
              for _, lbl in STAT_DISPLAY}
    # FG%/FT% need makes/attempts for combining; ESPN gives us the % value only,
    # so we carry forward the projected portion for a rough combined estimate.
    final_rows = []
    for _, name in STAT_DISPLAY:
        cur  = my_raw.get(name, 0)
        proj = proj_totals.get(
            next(sid for sid, lbl in STAT_DISPLAY if lbl == name), 0
        )
        final_rows.append([name, round(cur, 1), round(proj, 1), round(cur + proj, 1)])

    for label in PCT_LABELS:
        cur_v  = float((my_stats.get(label) or {}).get('value', 0) or 0)
        if 0 < cur_v <= 1.0: cur_v *= 100
        mid, aid = ('13', '14') if label == 'FG%' else ('15', '16')
        p_m = proj_totals.get(mid, 0)
        p_a = proj_totals.get(aid, 0)
        proj_pct = round(p_m / p_a * 100, 1) if p_a else 0.0
        final_rows.append([label, f"{round(cur_v, 1)}%", f"{proj_pct:.1f}%", "—"])

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
