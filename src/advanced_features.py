"""Advanced Feature Engineering for Maximum NRFI/YRFI Prediction Precision

Implements critical features identified for 60%+ accuracy:
- First-inning-specific pitcher stats (FI-ERA, FI-WHIP, FI-K%)
- Platoon splits against actual lineup
- Umpire strike zone metrics
- Real-time weather at first pitch
- First-inning park factors
- Top-3 hitter recent performance
- First-pitch strike percentages
"""

import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import statsapi
from pybaseball import statcast_pitcher, statcast_batter
import os


class AdvancedFeatureEngine:
    def __init__(self):
        self.sportsdata_key = os.getenv('SPORTSDATA_API_KEY')
        self.weather_api_key = os.getenv('WEATHER_API_KEY', '')  # Add OpenWeather or similar
        
    def get_first_inning_pitcher_stats(self, pitcher_id: int, season: int = 2026) -> Dict:
        """Get pitcher's first-inning-specific statistics
        
        FI-ERA can differ 2+ runs from overall ERA - critical for accuracy
        """
        try:
            # Query Statcast for first inning specific stats
            data = statcast_pitcher(
                f'{season}-04-01', 
                f'{season}-10-31', 
                pitcher_id
            )
            
            if data is None or data.empty:
                return self._get_default_fi_stats()
            
            # Filter for first inning only
            first_inning = data[data['inning'] == 1]
            
            if first_inning.empty:
                return self._get_default_fi_stats()
            
            # Calculate first-inning metrics
            innings_pitched = len(first_inning) / 3  # Approximate
            runs_allowed = first_inning['events'].isin(['run', 'home_run']).sum()
            hits_allowed = first_inning['events'].isin(
                ['single', 'double', 'triple', 'home_run']
            ).sum()
            walks = first_inning['events'].isin(['walk']).sum()
            strikeouts = first_inning['events'].isin(['strikeout']).sum()
            
            fi_era = (runs_allowed / max(innings_pitched, 0.1)) * 9
            fi_whip = (hits_allowed + walks) / max(innings_pitched, 0.1)
            fi_k_pct = strikeouts / max(len(first_inning), 1)
            
            # Calculate NRFI success rate
            games_pitched = first_inning.groupby('game_date').size().shape[0]
            scoreless_first = first_inning.groupby('game_date')['events'].apply(
                lambda x: not x.isin(['run', 'home_run']).any()
            ).sum()
            nrfi_rate = scoreless_first / max(games_pitched, 1)
            
            return {
                'fi_era': round(fi_era, 2),
                'fi_whip': round(fi_whip, 2),
                'fi_k_pct': round(fi_k_pct, 3),
                'fi_bb_pct': round(walks / max(len(first_inning), 1), 3),
                'nrfi_rate': round(nrfi_rate, 3),
                'fi_games': games_pitched,
                'first_pitch_strike_pct': self._calc_first_pitch_strikes(first_inning)
            }
            
        except Exception as e:
            print(f"Error fetching FI stats for pitcher {pitcher_id}: {e}")
            return self._get_default_fi_stats()
    
    def _calc_first_pitch_strikes(self, inning_data: pd.DataFrame) -> float:
        """Calculate first-pitch strike percentage
        
        66.8% of strikeouts start with first-pitch strikes
        74.3% of walks start with first-pitch balls
        """
        if inning_data.empty:
            return 0.65
        
        first_pitches = inning_data.groupby(['game_date', 'at_bat_number']).first()
        strikes = first_pitches['type'].isin(['S', 'X']).sum()
        return strikes / max(len(first_pitches), 1)
    
    def _get_default_fi_stats(self) -> Dict:
        """Default stats when data unavailable"""
        return {
            'fi_era': 4.20,
            'fi_whip': 1.30,
            'fi_k_pct': 0.22,
            'fi_bb_pct': 0.09,
            'nrfi_rate': 0.65,
            'fi_games': 0,
            'first_pitch_strike_pct': 0.63
        }
    
    def get_platoon_splits_vs_lineup(self, pitcher_id: int, lineup: List[Dict]) -> Dict:
        """Get pitcher's splits against today's specific lineup handedness
        
        Top 3 batters matter most - they're the only ones guaranteed to bat in 1st inning
        Platoon advantage creates 3-4% probability shift
        """
        try:
            # Get pitcher's splits
            pitcher_data = statcast_pitcher(
                f'{datetime.now().year}-04-01',
                datetime.now().strftime('%Y-%m-%d'),
                pitcher_id
            )
            
            if pitcher_data is None or pitcher_data.empty:
                return {'platoon_advantage': 0.0, 'woba_vs_top3': 0.320}
            
            # Focus on top 3 batters
            top_3_batters = lineup[:3]
            lhb_count = sum(1 for b in top_3_batters if b.get('bats') == 'L')
            rhb_count = 3 - lhb_count
            
            # Calculate wOBA against LHB and RHB
            lhb_data = pitcher_data[pitcher_data['stand'] == 'L']
            rhb_data = pitcher_data[pitcher_data['stand'] == 'R']
            
            lhb_woba = self._calc_woba(lhb_data) if not lhb_data.empty else 0.320
            rhb_woba = self._calc_woba(rhb_data) if not rhb_data.empty else 0.320
            
            # Weighted average based on lineup
            weighted_woba = (lhb_woba * lhb_count + rhb_woba * rhb_count) / 3
            
            # Platoon advantage (negative = pitcher advantage)
            platoon_advantage = weighted_woba - 0.320  # League average ~.320
            
            return {
                'platoon_advantage': round(platoon_advantage, 3),
                'woba_vs_top3': round(weighted_woba, 3),
                'lhb_in_top3': lhb_count,
                'rhb_in_top3': rhb_count
            }
            
        except Exception as e:
            print(f"Error calculating platoon splits: {e}")
            return {'platoon_advantage': 0.0, 'woba_vs_top3': 0.320}
    
    def _calc_woba(self, data: pd.DataFrame) -> float:
        """Calculate weighted on-base average"""
        if data.empty:
            return 0.320
        
        weights = {'walk': 0.69, 'single': 0.88, 'double': 1.24, 
                   'triple': 1.56, 'home_run': 1.95}
        
        total_value = sum(
            data['events'].isin([event]).sum() * weight 
            for event, weight in weights.items()
        )
        
        pa = len(data)
        return total_value / max(pa, 1)
    
    def get_umpire_metrics(self, umpire_name: str) -> Dict:
        """Get umpire strike zone metrics from Baseball Savant
        
        Top 10% zone size shifts NRFI probability 3-4 percentage points
        Larger zones = more pitcher-friendly = more NRFI
        """
        try:
            # In production, scrape from Baseball Savant umpire scorecards
            # For now, use cached/database lookup
            
            # Placeholder - replace with actual Baseball Savant API/scraping
            umpire_db = {
                'Pat Hoberg': {'zone_size_pct': 95, 'consistency': 98},
                'Angel Hernandez': {'zone_size_pct': 20, 'consistency': 45},
                'Joe West': {'zone_size_pct': 85, 'consistency': 75},
            }
            
            ump_data = umpire_db.get(umpire_name, {'zone_size_pct': 50, 'consistency': 70})
            
            # Convert to NRFI probability adjustment
            # Top 10% (90+) = +0.03 to NRFI prob
            # Bottom 10% (<20) = -0.03 to NRFI prob
            zone_adj = (ump_data['zone_size_pct'] - 50) / 1000
            
            return {
                'umpire_name': umpire_name,
                'zone_size_percentile': ump_data['zone_size_pct'],
                'nrfi_probability_adj': round(zone_adj, 3),
                'consistency_score': ump_data['consistency']
            }
            
        except Exception as e:
            print(f"Error fetching umpire data: {e}")
            return {
                'umpire_name': umpire_name,
                'zone_size_percentile': 50,
                'nrfi_probability_adj': 0.0,
                'consistency_score': 70
            }
    
    def get_weather_at_first_pitch(self, game_id: int, stadium: str) -> Dict:
        """Get real-time weather conditions at first pitch time
        
        Cold (<50°F) suppresses scoring significantly
        Wind blowing in from CF = NRFI favorable
        Wind blowing out = YRFI favorable
        """
        try:
            # Get game time
            game_info = statsapi.get('game', {'gamePk': game_id})
            first_pitch_time = game_info.get('gameData', {}).get('datetime', {}).get('dateTime')
            
            # Get stadium coordinates (cached)
            stadium_coords = self._get_stadium_coords(stadium)
            
            if not self.weather_api_key or not stadium_coords:
                return self._get_default_weather()
            
            # Call weather API (OpenWeather, Weather.gov, etc.)
            weather_url = f"https://api.openweathermap.org/data/2.5/weather"
            params = {
                'lat': stadium_coords['lat'],
                'lon': stadium_coords['lon'],
                'appid': self.weather_api_key,
                'units': 'imperial'
            }
            
            response = requests.get(weather_url, params=params, timeout=5)
            weather = response.json()
            
            temp = weather.get('main', {}).get('temp', 70)
            wind_speed = weather.get('wind', {}).get('speed', 5)
            wind_dir = weather.get('wind', {}).get('deg', 0)
            
            # Calculate wind effect (simplified)
            # 0-45° or 315-360° = blowing out to CF
            # 135-225° = blowing in from CF
            wind_effect = 0.0
            if 135 <= wind_dir <= 225:  # Blowing in
                wind_effect = -wind_speed * 0.002  # Favor NRFI
            elif (wind_dir >= 315 or wind_dir <= 45):  # Blowing out
                wind_effect = wind_speed * 0.002  # Favor YRFI
            
            # Temperature effect
            temp_effect = 0.0
            if temp < 50:
                temp_effect = -0.03  # Strong NRFI favor
            elif temp > 85:
                temp_effect = 0.015  # Slight YRFI favor
            
            return {
                'temperature_f': round(temp, 1),
                'wind_speed_mph': round(wind_speed, 1),
                'wind_direction': wind_dir,
                'nrfi_temp_adj': round(temp_effect, 3),
                'nrfi_wind_adj': round(wind_effect, 3),
                'total_weather_adj': round(temp_effect + wind_effect, 3)
            }
            
        except Exception as e:
            print(f"Error fetching weather: {e}")
            return self._get_default_weather()
    
    def _get_stadium_coords(self, stadium: str) -> Optional[Dict]:
        """Get stadium GPS coordinates"""
        coords = {
            'Yankee Stadium': {'lat': 40.8296, 'lon': -73.9262},
            'Fenway Park': {'lat': 42.3467, 'lon': -71.0972},
            'Wrigley Field': {'lat': 41.9484, 'lon': -87.6553},
            'Dodger Stadium': {'lat': 34.0739, 'lon': -118.2400},
            'Oracle Park': {'lat': 37.7786, 'lon': -122.3893},
            'Coors Field': {'lat': 39.7559, 'lon': -104.9942},
            # Add all 30 stadiums
        }
        return coords.get(stadium)
    
    def _get_default_weather(self) -> Dict:
        """Default weather when API unavailable"""
        return {
            'temperature_f': 72.0,
            'wind_speed_mph': 5.0,
            'wind_direction': 180,
            'nrfi_temp_adj': 0.0,
            'nrfi_wind_adj': 0.0,
            'total_weather_adj': 0.0
        }
    
    def get_first_inning_park_factor(self, stadium: str) -> float:
        """Get park-specific first-inning run factor
        
        Not all parks equal - Oracle/Petco suppress, Coors/GABP inflate
        """
        # First-inning specific park factors (100 = league average)
        fi_park_factors = {
            'Oracle Park': 78,  # Very pitcher-friendly
            'Petco Park': 82,
            'Dodger Stadium': 88,
            'Citi Field': 91,
            'T-Mobile Park': 92,
            'Fenway Park': 105,
            'Yankee Stadium': 108,
            'Citizens Bank Park': 110,
            'Great American Ball Park': 118,
            'Coors Field': 125,  # Very hitter-friendly
            # Add remaining stadiums
        }
        
        factor = fi_park_factors.get(stadium, 100)
        
        # Convert to NRFI probability adjustment
        # 78 (Oracle) = +0.04 NRFI prob
        # 125 (Coors) = -0.04 NRFI prob
        park_adj = (100 - factor) / 600
        
        return round(park_adj, 3)
    
    def get_top3_recent_performance(self, lineup: List[Dict]) -> Dict:
        """Get last 14-day OPS for batters 1-3 in lineup
        
        If all struggling (<.600 OPS), NRFI probability increases
        """
        try:
            top_3 = lineup[:3]
            ops_values = []
            
            for batter in top_3:
                batter_id = batter.get('id')
                if not batter_id:
                    ops_values.append(0.720)  # League average
                    continue
                
                # Get last 14 days stats
                end_date = datetime.now()
                start_date = end_date - timedelta(days=14)
                
                data = statcast_batter(
                    start_date.strftime('%Y-%m-%d'),
                    end_date.strftime('%Y-%m-%d'),
                    batter_id
                )
                
                if data is None or data.empty:
                    ops_values.append(0.720)
                    continue
                
                # Calculate OPS (simplified)
                pa = len(data)
                hits = data['events'].isin(['single', 'double', 'triple', 'home_run']).sum()
                walks = data['events'].isin(['walk']).sum()
                total_bases = (
                    data['events'].isin(['single']).sum() +
                    data['events'].isin(['double']).sum() * 2 +
                    data['events'].isin(['triple']).sum() * 3 +
                    data['events'].isin(['home_run']).sum() * 4
                )
                
                obp = (hits + walks) / max(pa, 1)
                slg = total_bases / max(pa, 1)
                ops = obp + slg
                
                ops_values.append(ops)
            
            avg_ops = np.mean(ops_values)
            
            # If all below .600, strong NRFI indicator
            struggling = all(ops < 0.600 for ops in ops_values)
            
            # Adjustment to NRFI probability
            ops_adj = (0.720 - avg_ops) * 0.1  # Scale factor
            
            return {
                'top3_avg_ops_l14': round(avg_ops, 3),
                'top3_struggling': struggling,
                'nrfi_ops_adj': round(ops_adj, 3),
                'individual_ops': [round(ops, 3) for ops in ops_values]
            }
            
        except Exception as e:
            print(f"Error calculating top-3 performance: {e}")
            return {
                'top3_avg_ops_l14': 0.720,
                'top3_struggling': False,
                'nrfi_ops_adj': 0.0,
                'individual_ops': [0.720, 0.720, 0.720]
            }
    
    def generate_advanced_features(self, game_data: Dict) -> Dict:
        """Generate complete feature set for maximum prediction precision
        
        Combines all high-impact features identified in research
        """
        # Extract game info
        home_pitcher_id = game_data.get('home_pitcher_id')
        away_pitcher_id = game_data.get('away_pitcher_id')
        home_lineup = game_data.get('home_lineup', [])
        away_lineup = game_data.get('away_lineup', [])
        umpire = game_data.get('umpire', 'Unknown')
        stadium = game_data.get('stadium', 'Unknown')
        game_id = game_data.get('game_id')
        
        # Get all features
        home_fi_stats = self.get_first_inning_pitcher_stats(home_pitcher_id)
        away_fi_stats = self.get_first_inning_pitcher_stats(away_pitcher_id)
        
        home_platoon = self.get_platoon_splits_vs_lineup(home_pitcher_id, away_lineup)
        away_platoon = self.get_platoon_splits_vs_lineup(away_pitcher_id, home_lineup)
        
        umpire_metrics = self.get_umpire_metrics(umpire)
        weather = self.get_weather_at_first_pitch(game_id, stadium)
        park_factor = self.get_first_inning_park_factor(stadium)
        
        home_top3 = self.get_top3_recent_performance(home_lineup)
        away_top3 = self.get_top3_recent_performance(away_lineup)
        
        # Combine into feature dictionary
        features = {
            # Home pitcher first-inning stats
            'home_fi_era': home_fi_stats['fi_era'],
            'home_fi_whip': home_fi_stats['fi_whip'],
            'home_fi_k_pct': home_fi_stats['fi_k_pct'],
            'home_nrfi_rate': home_fi_stats['nrfi_rate'],
            'home_first_pitch_strike_pct': home_fi_stats['first_pitch_strike_pct'],
            
            # Away pitcher first-inning stats
            'away_fi_era': away_fi_stats['fi_era'],
            'away_fi_whip': away_fi_stats['fi_whip'],
            'away_fi_k_pct': away_fi_stats['fi_k_pct'],
            'away_nrfi_rate': away_fi_stats['nrfi_rate'],
            'away_first_pitch_strike_pct': away_fi_stats['first_pitch_strike_pct'],
            
            # Platoon matchups
            'home_platoon_advantage': home_platoon['platoon_advantage'],
            'away_platoon_advantage': away_platoon['platoon_advantage'],
            
            # Umpire
            'umpire_zone_percentile': umpire_metrics['zone_size_percentile'],
            'umpire_nrfi_adj': umpire_metrics['nrfi_probability_adj'],
            
            # Weather
            'temperature': weather['temperature_f'],
            'wind_speed': weather['wind_speed_mph'],
            'weather_nrfi_adj': weather['total_weather_adj'],
            
            # Park
            'park_nrfi_adj': park_factor,
            
            # Offense
            'home_top3_ops_l14': home_top3['top3_avg_ops_l14'],
            'away_top3_ops_l14': away_top3['top3_avg_ops_l14'],
            'home_top3_struggling': home_top3['top3_struggling'],
            'away_top3_struggling': away_top3['top3_struggling'],
            
            # Combined pitcher quality
            'avg_fi_era': (home_fi_stats['fi_era'] + away_fi_stats['fi_era']) / 2,
            'avg_nrfi_rate': (home_fi_stats['nrfi_rate'] + away_fi_stats['nrfi_rate']) / 2,
            
            # Total adjustments
            'total_nrfi_adj': (
                umpire_metrics['nrfi_probability_adj'] +
                weather['total_weather_adj'] +
                park_factor +
                home_top3['nrfi_ops_adj'] +
                away_top3['nrfi_ops_adj']
            )
        }
        
        return features


if __name__ == '__main__':
    # Test the feature engine
    engine = AdvancedFeatureEngine()
    
    test_game = {
        'game_id': 12345,
        'home_pitcher_id': 543243,
        'away_pitcher_id': 605483,
        'home_lineup': [{'id': 660271, 'bats': 'L'}] * 3,
        'away_lineup': [{'id': 592450, 'bats': 'R'}] * 3,
        'umpire': 'Pat Hoberg',
        'stadium': 'Oracle Park'
    }
    
    features = engine.generate_advanced_features(test_game)
    print("\nAdvanced Features Generated:")
    for key, value in features.items():
        print(f"{key}: {value}")
