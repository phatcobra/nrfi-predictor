"""Feature engineering for NRFI/YRFI prediction.

Comprehensive feature generation from:
- Pitcher stats (career, recent, vs handedness, first-inning splits)
- Team offense stats (career, recent, vs handedness, first-inning performance)
- Park factors and weather
- Matchup history
- Lineup quality
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
from snowflake_loader import SnowflakeLoader

logger = logging.getLogger(__name__)


class NFRIFeatureEngineer:
    """Generate features for NRFI/YRFI prediction."""
    
    def __init__(self, snowflake_loader: Optional[SnowflakeLoader] = None):
        """Initialize feature engineer.
        
        Args:
            snowflake_loader: Optional Snowflake connection for data access
        """
        self.sf = snowflake_loader or SnowflakeLoader()
        self.lookback_days = [7, 14, 30, 90, 365]  # Different time windows
        
    def generate_game_features(self, game_data: Dict) -> Dict:
        """Generate all features for a single game.
        
        Args:
            game_data: Dict containing game info (game_id, date, teams, pitchers, etc.)
            
        Returns:
            Dict of features ready for model input
        """
        game_date = pd.to_datetime(game_data['game_date'])
        away_team = game_data['away_team']
        home_team = game_data['home_team']
        away_pitcher = game_data['away_pitcher_id']
        home_pitcher = game_data['home_pitcher_id']
        
        features = {}
        
        # Pitcher features
        features.update(self._get_pitcher_features(away_pitcher, 'away', game_date))
        features.update(self._get_pitcher_features(home_pitcher, 'home', game_date))
        
        # Team offense features
        features.update(self._get_team_offense_features(away_team, 'away', game_date))
        features.update(self._get_team_offense_features(home_team, 'home', game_date))
        
        # Matchup features
        features.update(self._get_matchup_features(
            away_pitcher, home_team, 'away', game_date
        ))
        features.update(self._get_matchup_features(
            home_pitcher, away_team, 'home', game_date
        ))
        
        # Park and weather features
        features.update(self._get_park_features(game_data.get('venue_id')))
        features.update(self._get_weather_features(game_data))
        
        # Lineup features (if available)
        if 'lineups' in game_data:
            features.update(self._get_lineup_features(game_data['lineups'], game_date))
            
        # Odds features (if available)
        if 'odds' in game_data:
            features.update(self._get_odds_features(game_data['odds']))
        
        return features
    
    def _get_pitcher_features(self, pitcher_id: str, side: str, game_date: datetime) -> Dict:
        """Extract pitcher features across multiple time windows."""
        features = {}
        
        # Career stats
        career_stats = self._query_pitcher_stats(pitcher_id, None, game_date)
        if career_stats is not None:
            features.update({
                f'{side}_p_career_era': career_stats.get('era', 0),
                f'{side}_p_career_whip': career_stats.get('whip', 0),
                f'{side}_p_career_k9': career_stats.get('k_per_9', 0),
                f'{side}_p_career_bb9': career_stats.get('bb_per_9', 0),
                f'{side}_p_career_ip': career_stats.get('total_ip', 0),
            })
        
        # First inning specific stats (career)
        first_inning_stats = self._query_pitcher_first_inning_stats(pitcher_id, None, game_date)
        if first_inning_stats is not None:
            features.update({
                f'{side}_p_first_inning_era': first_inning_stats.get('era', 0),
                f'{side}_p_first_inning_whip': first_inning_stats.get('whip', 0),
                f'{side}_p_first_inning_runs_allowed_rate': first_inning_stats.get('runs_per_game', 0),
                f'{side}_p_first_inning_nrfi_pct': first_inning_stats.get('nrfi_pct', 0.5),
            })
        
        # Recent form (multiple windows)
        for days in self.lookback_days:
            recent_stats = self._query_pitcher_stats(
                pitcher_id, 
                game_date - timedelta(days=days),
                game_date
            )
            if recent_stats is not None:
                features.update({
                    f'{side}_p_{days}d_era': recent_stats.get('era', 0),
                    f'{side}_p_{days}d_whip': recent_stats.get('whip', 0),
                    f'{side}_p_{days}d_starts': recent_stats.get('games_started', 0),
                })
                
        # Statcast metrics (if available)
        statcast = self._query_statcast_pitcher(pitcher_id, game_date)
        if statcast is not None:
            features.update({
                f'{side}_p_avg_exit_velo': statcast.get('avg_exit_velocity', 88.0),
                f'{side}_p_barrel_pct': statcast.get('barrel_pct', 8.0),
                f'{side}_p_hard_hit_pct': statcast.get('hard_hit_pct', 40.0),
                f'{side}_p_whiff_pct': statcast.get('whiff_pct', 25.0),
                f'{side}_p_chase_pct': statcast.get('chase_pct', 30.0),
            })
        
        return features
    
    def _get_team_offense_features(self, team: str, side: str, game_date: datetime) -> Dict:
        """Extract team offense features."""
        features = {}
        
        # Season stats
        season_stats = self._query_team_offense_stats(team, None, game_date)
        if season_stats is not None:
            features.update({
                f'{side}_t_season_avg': season_stats.get('batting_avg', 0.250),
                f'{side}_t_season_obp': season_stats.get('obp', 0.320),
                f'{side}_t_season_slg': season_stats.get('slg', 0.400),
                f'{side}_t_season_woba': season_stats.get('woba', 0.320),
                f'{side}_t_season_runs_per_game': season_stats.get('runs_per_game', 4.5),
            })
        
        # First inning stats
        first_inning_offense = self._query_team_first_inning_offense(team, None, game_date)
        if first_inning_offense is not None:
            features.update({
                f'{side}_t_first_inning_runs_per_game': first_inning_offense.get('runs_per_game', 0.3),
                f'{side}_t_first_inning_scoring_pct': first_inning_offense.get('scoring_pct', 0.25),
                f'{side}_t_first_inning_avg': first_inning_offense.get('batting_avg', 0.240),
            })
        
        # Recent form
        for days in [7, 14, 30]:
            recent = self._query_team_offense_stats(
                team,
                game_date - timedelta(days=days),
                game_date
            )
            if recent is not None:
                features.update({
                    f'{side}_t_{days}d_runs_per_game': recent.get('runs_per_game', 4.5),
                    f'{side}_t_{days}d_woba': recent.get('woba', 0.320),
                })
        
        # Statcast team offense
        statcast_team = self._query_statcast_team_offense(team, game_date)
        if statcast_team is not None:
            features.update({
                f'{side}_t_avg_exit_velo': statcast_team.get('avg_exit_velocity', 88.0),
                f'{side}_t_barrel_pct': statcast_team.get('barrel_pct', 7.0),
                f'{side}_t_hard_hit_pct': statcast_team.get('hard_hit_pct', 38.0),
            })
        
        return features
    
    def _get_matchup_features(self, pitcher_id: str, opponent_team: str, 
                             side: str, game_date: datetime) -> Dict:
        """Features for specific pitcher vs team matchups."""
        features = {}
        
        # Historical performance vs this team
        matchup_history = self._query_pitcher_vs_team(
            pitcher_id, opponent_team, game_date
        )
        if matchup_history is not None:
            features.update({
                f'{side}_matchup_games': matchup_history.get('games', 0),
                f'{side}_matchup_era': matchup_history.get('era', 0),
                f'{side}_matchup_whip': matchup_history.get('whip', 0),
                f'{side}_matchup_runs_per_game': matchup_history.get('runs_per_game', 0),
            })
        
        return features
    
    def _get_park_features(self, venue_id: Optional[str]) -> Dict:
        """Park factor features."""
        if venue_id is None:
            return {}
        
        park_factors = self._query_park_factors(venue_id)
        if park_factors is None:
            return {}
        
        return {
            'park_runs_factor': park_factors.get('runs_factor', 1.0),
            'park_hr_factor': park_factors.get('hr_factor', 1.0),
            'park_hits_factor': park_factors.get('hits_factor', 1.0),
        }
    
    def _get_weather_features(self, game_data: Dict) -> Dict:
        """Weather features if available."""
        weather = game_data.get('weather', {})
        
        return {
            'temp_f': weather.get('temperature', 70.0),
            'wind_speed': weather.get('wind_speed', 5.0),
            'is_dome': 1 if game_data.get('is_dome', False) else 0,
        }
    
    def _get_lineup_features(self, lineups: Dict, game_date: datetime) -> Dict:
        """Features based on batting lineups (top of order quality)."""
        features = {}
        
        for side in ['away', 'home']:
            if side not in lineups:
                continue
            
            # Top 3 batters
            top_3 = lineups[side][:3] if len(lineups[side]) >= 3 else lineups[side]
            
            top_3_stats = []
            for batter_id in top_3:
                stats = self._query_batter_stats(batter_id, game_date)
                if stats:
                    top_3_stats.append(stats)
            
            if top_3_stats:
                features.update({
                    f'{side}_lineup_top3_avg_woba': np.mean([s.get('woba', 0.320) for s in top_3_stats]),
                    f'{side}_lineup_top3_avg_obp': np.mean([s.get('obp', 0.320) for s in top_3_stats]),
                })
        
        return features
    
    def _get_odds_features(self, odds: Dict) -> Dict:
        """Features from betting odds."""
        features = {}
        
        # NRFI/YRFI odds (if available)
        if 'nrfi_yes' in odds:
            features['nrfi_yes_odds'] = self._american_to_prob(odds['nrfi_yes'])
        if 'nrfi_no' in odds:
            features['nrfi_no_odds'] = self._american_to_prob(odds['nrfi_no'])
        
        # Total runs line
        if 'total_line' in odds:
            features['total_runs_line'] = odds['total_line']
        
        # Moneyline (team strength proxy)
        if 'away_ml' in odds:
            features['away_implied_wp'] = self._american_to_prob(odds['away_ml'])
        if 'home_ml' in odds:
            features['home_implied_wp'] = self._american_to_prob(odds['home_ml'])
        
        return features
    
    @staticmethod
    def _american_to_prob(american_odds: float) -> float:
        """Convert American odds to implied probability."""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
    
    # Database query methods (use Snowflake)
    
    def _query_pitcher_stats(self, pitcher_id: str, start_date: Optional[datetime], 
                           end_date: datetime) -> Optional[Dict]:
        """Query pitcher stats from Snowflake."""
        query = """
        SELECT 
            AVG(earned_runs * 9.0 / NULLIF(innings_pitched, 0)) as era,
            AVG((hits + walks) / NULLIF(innings_pitched, 0)) as whip,
            AVG(strikeouts * 9.0 / NULLIF(innings_pitched, 0)) as k_per_9,
            AVG(walks * 9.0 / NULLIF(innings_pitched, 0)) as bb_per_9,
            SUM(innings_pitched) as total_ip,
            COUNT(*) as games_started
        FROM nrfi_db.raw.pitcher_game_logs
        WHERE pitcher_id = %s
          AND game_date < %s
        """
        
        params = [pitcher_id, end_date]
        if start_date:
            query += " AND game_date >= %s"
            params.append(start_date)
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying pitcher stats: {e}")
        
        return None
    
    def _query_pitcher_first_inning_stats(self, pitcher_id: str, 
                                         start_date: Optional[datetime],
                                         end_date: datetime) -> Optional[Dict]:
        """Query first inning specific stats."""
        query = """
        SELECT 
            AVG(first_inning_runs) as runs_per_game,
            AVG(first_inning_hits + first_inning_walks) as baserunners_per_game,
            AVG(CASE WHEN first_inning_runs = 0 THEN 1.0 ELSE 0.0 END) as nrfi_pct,
            AVG(first_inning_runs * 9.0) as era,
            AVG(first_inning_hits + first_inning_walks) as whip
        FROM nrfi_db.raw.pitcher_inning_logs
        WHERE pitcher_id = %s
          AND inning = 1
          AND game_date < %s
        """
        
        params = [pitcher_id, end_date]
        if start_date:
            query += " AND game_date >= %s"
            params.append(start_date)
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying first inning stats: {e}")
        
        return None
    
    def _query_statcast_pitcher(self, pitcher_id: str, game_date: datetime) -> Optional[Dict]:
        """Query Statcast pitcher metrics."""
        # Last 30 days of Statcast data
        query = """
        SELECT 
            AVG(exit_velocity) as avg_exit_velocity,
            AVG(CASE WHEN barrel = 1 THEN 1.0 ELSE 0.0 END) * 100 as barrel_pct,
            AVG(CASE WHEN exit_velocity >= 95 THEN 1.0 ELSE 0.0 END) * 100 as hard_hit_pct,
            AVG(CASE WHEN swing = 1 AND contact = 0 THEN 1.0 ELSE 0.0 END) * 100 as whiff_pct
        FROM nrfi_db.raw.statcast_pitcher
        WHERE pitcher_id = %s
          AND game_date < %s
          AND game_date >= %s
        """
        
        params = [pitcher_id, game_date, game_date - timedelta(days=30)]
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying Statcast pitcher: {e}")
        
        return None
    
    def _query_team_offense_stats(self, team: str, start_date: Optional[datetime],
                                 end_date: datetime) -> Optional[Dict]:
        """Query team offense stats."""
        query = """
        SELECT 
            AVG(batting_avg) as batting_avg,
            AVG(on_base_pct) as obp,
            AVG(slugging_pct) as slg,
            AVG(woba) as woba,
            AVG(runs) as runs_per_game
        FROM nrfi_db.raw.team_game_logs
        WHERE team = %s
          AND game_date < %s
        """
        
        params = [team, end_date]
        if start_date:
            query += " AND game_date >= %s"
            params.append(start_date)
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying team offense: {e}")
        
        return None
    
    def _query_team_first_inning_offense(self, team: str, start_date: Optional[datetime],
                                        end_date: datetime) -> Optional[Dict]:
        """Query team first inning offense."""
        query = """
        SELECT 
            AVG(first_inning_runs) as runs_per_game,
            AVG(CASE WHEN first_inning_runs > 0 THEN 1.0 ELSE 0.0 END) as scoring_pct,
            AVG(first_inning_batting_avg) as batting_avg
        FROM nrfi_db.raw.team_inning_logs
        WHERE team = %s
          AND inning = 1
          AND game_date < %s
        """
        
        params = [team, end_date]
        if start_date:
            query += " AND game_date >= %s"
            params.append(start_date)
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying team first inning offense: {e}")
        
        return None
    
    def _query_statcast_team_offense(self, team: str, game_date: datetime) -> Optional[Dict]:
        """Query Statcast team offense metrics."""
        query = """
        SELECT 
            AVG(exit_velocity) as avg_exit_velocity,
            AVG(CASE WHEN barrel = 1 THEN 1.0 ELSE 0.0 END) * 100 as barrel_pct,
            AVG(CASE WHEN exit_velocity >= 95 THEN 1.0 ELSE 0.0 END) * 100 as hard_hit_pct
        FROM nrfi_db.raw.statcast_batter
        WHERE team = %s
          AND game_date < %s
          AND game_date >= %s
        """
        
        params = [team, game_date, game_date - timedelta(days=30)]
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying Statcast team offense: {e}")
        
        return None
    
    def _query_pitcher_vs_team(self, pitcher_id: str, team: str, 
                              game_date: datetime) -> Optional[Dict]:
        """Query pitcher vs specific team history."""
        query = """
        SELECT 
            COUNT(*) as games,
            AVG(earned_runs * 9.0 / NULLIF(innings_pitched, 0)) as era,
            AVG((hits + walks) / NULLIF(innings_pitched, 0)) as whip,
            AVG(earned_runs) as runs_per_game
        FROM nrfi_db.raw.pitcher_game_logs
        WHERE pitcher_id = %s
          AND opponent_team = %s
          AND game_date < %s
        """
        
        params = [pitcher_id, team, game_date]
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying pitcher vs team: {e}")
        
        return None
    
    def _query_park_factors(self, venue_id: str) -> Optional[Dict]:
        """Query park factors."""
        query = """
        SELECT 
            runs_factor,
            hr_factor,
            hits_factor
        FROM nrfi_db.raw.park_factors
        WHERE venue_id = %s
        """
        
        try:
            result = self.sf.execute_query(query, [venue_id])
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying park factors: {e}")
        
        return None
    
    def _query_batter_stats(self, batter_id: str, game_date: datetime) -> Optional[Dict]:
        """Query batter stats for lineup analysis."""
        query = """
        SELECT 
            AVG(woba) as woba,
            AVG(on_base_pct) as obp,
            AVG(slugging_pct) as slg
        FROM nrfi_db.raw.batter_game_logs
        WHERE batter_id = %s
          AND game_date < %s
          AND game_date >= %s
        """
        
        params = [batter_id, game_date, game_date - timedelta(days=30)]
        
        try:
            result = self.sf.execute_query(query, params)
            if result and len(result) > 0:
                return result[0]
        except Exception as e:
            logger.error(f"Error querying batter stats: {e}")
        
        return None


if __name__ == "__main__":
    # Example usage
    engineer = NFRIFeatureEngineer()
    
    sample_game = {
        'game_id': 'game_123',
        'game_date': '2024-06-15',
        'away_team': 'NYY',
        'home_team': 'BOS',
        'away_pitcher_id': 'cole_g01',
        'home_pitcher_id': 'sale_c01',
        'venue_id': 'BOS01',
        'weather': {'temperature': 75, 'wind_speed': 8},
    }
    
    features = engineer.generate_game_features(sample_game)
    print(f"Generated {len(features)} features")
    print(features)
