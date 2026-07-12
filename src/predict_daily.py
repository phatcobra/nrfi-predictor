"""Daily NRFI/YRFI predictions for all MLB games.

Generate predictions for today's games using:
- Latest trained model
- Fresh data from SportsDataIO and OpticOdds
- Feature engineering pipeline
- Save predictions to Snowflake
- Expose via API
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict
import logging
import json
import os
import sentry_sdk
from snowflake_loader import SnowflakeLoader
from features import NFRIFeatureEngineer
from train import NFRIModelTrainer
from ingest_sportsdata import SportsDataIOIngester
from ingest_opticodds import OpticOddsIngester
from config import Config

logger = logging.getLogger(__name__)

# Initialize Sentry
try:
    sentry_sdk.init(
        dsn=os.getenv('SENTRY_DSN'),
        environment=os.getenv('ENV', 'production'),
        traces_sample_rate=0.1,
    )
except Exception as e:
    logger.warning(f"Sentry initialization failed: {e}")


class NFRIDailyPredictor:
    """Generate daily NRFI/YRFI predictions."""
    
    def __init__(self, model_version: str = None, config: Config = None):
        """Initialize daily predictor.
        
        Args:
            model_version: Specific model version to use (default: latest)
            config: Configuration object
        """
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.feature_engineer = NFRIFeatureEngineer(self.sf)
        self.sdio_ingester = SportsDataIOIngester()
        self.odds_ingester = OpticOddsIngester()
        
        # Load model
        self.trainer = NFRIModelTrainer()
        if model_version:
            self.trainer.load_model(self.config.MODEL_DIR, model_version)
        else:
            # Load latest model
            self.trainer.load_model(self.config.MODEL_DIR, self._get_latest_model_version())
        
        logger.info(f"Loaded model for predictions")
    
    def _get_latest_model_version(self) -> str:
        """Get the latest model version from model directory."""
        import glob
        model_files = glob.glob(f"{self.config.MODEL_DIR}/nrfi_model_*.txt")
        if not model_files:
            raise ValueError("No trained models found")
        
        # Extract versions from filenames
        versions = [f.split('_')[-1].replace('.txt', '') for f in model_files]
        return sorted(versions)[-1]
    
    def get_todays_games(self, target_date: str = None) -> List[Dict]:
        """Fetch today's scheduled games.
        
        Args:
            target_date: Date to predict (YYYY-MM-DD), default today
            
        Returns:
            List of game dicts with metadata
        """
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"Fetching games for {target_date}")
        
        try:
            # Get games from SportsDataIO
            games = self.sdio_ingester.get_schedule(target_date)
            
            # Get odds from OpticOdds
            odds_data = self.odds_ingester.get_nrfi_odds(target_date)
            
            # Merge odds into games
            games_with_odds = []
            for game in games:
                game_odds = odds_data.get(game['game_id'], {})
                game['odds'] = game_odds
                games_with_odds.append(game)
            
            logger.info(f"Found {len(games_with_odds)} games for {target_date}")
            return games_with_odds
            
        except Exception as e:
            logger.error(f"Error fetching games: {e}")
            sentry_sdk.capture_exception(e)
            raise
    
    def generate_predictions(self, games: List[Dict]) -> pd.DataFrame:
        """Generate NRFI predictions for games.
        
        Args:
            games: List of game dicts
            
        Returns:
            DataFrame with predictions
        """
        logger.info(f"Generating predictions for {len(games)} games")
        
        predictions = []
        
        for game in games:
            try:
                # Generate features
                features = self.feature_engineer.generate_game_features(game)
                
                # Convert to feature vector
                feature_vector = [features.get(fname, 0) for fname in self.trainer.feature_names]
                X = np.array([feature_vector])
                
                # Get prediction
                if self.trainer.calibrated_model:
                    # Use calibrated probabilities
                    nrfi_prob = self.trainer.calibrated_model.predict_proba(X)[0][1]
                else:
                    # Use raw LightGBM probabilities
                    nrfi_prob = self.trainer.model.predict(X)[0]
                
                yrfi_prob = 1 - nrfi_prob
                
                # Determine recommended bet
                confidence_threshold = 0.60  # Only recommend if >60% confident
                
                if nrfi_prob >= confidence_threshold:
                    recommendation = 'NRFI'
                    confidence = nrfi_prob
                elif yrfi_prob >= confidence_threshold:
                    recommendation = 'YRFI'
                    confidence = yrfi_prob
                else:
                    recommendation = 'PASS'
                    confidence = max(nrfi_prob, yrfi_prob)
                
                # Compare to odds (if available)
                edge = None
                if game.get('odds', {}).get('nrfi_yes'):
                    odds_nrfi_prob = self._american_to_prob(game['odds']['nrfi_yes'])
                    edge = nrfi_prob - odds_nrfi_prob  # Positive edge = bet value
                
                prediction = {
                    'game_id': game['game_id'],
                    'game_date': game['game_date'],
                    'game_time': game.get('game_time', 'TBD'),
                    'away_team': game['away_team'],
                    'home_team': game['home_team'],
                    'away_pitcher': game.get('away_pitcher_name', 'TBD'),
                    'home_pitcher': game.get('home_pitcher_name', 'TBD'),
                    'nrfi_probability': round(nrfi_prob, 4),
                    'yrfi_probability': round(yrfi_prob, 4),
                    'recommendation': recommendation,
                    'confidence': round(confidence, 4),
                    'edge_vs_odds': round(edge, 4) if edge is not None else None,
                    'nrfi_odds': game.get('odds', {}).get('nrfi_yes'),
                    'yrfi_odds': game.get('odds', {}).get('nrfi_no'),
                    'prediction_timestamp': datetime.now().isoformat(),
                }
                
                predictions.append(prediction)
                
            except Exception as e:
                logger.warning(f"Error predicting game {game.get('game_id')}: {e}")
                sentry_sdk.capture_exception(e)
                continue
        
        df = pd.DataFrame(predictions)
        logger.info(f"Generated {len(df)} predictions")
        
        return df
    
    @staticmethod
    def _american_to_prob(american_odds: float) -> float:
        """Convert American odds to probability."""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
    
    def save_predictions(self, predictions_df: pd.DataFrame):
        """Save predictions to Snowflake.
        
        Args:
            predictions_df: DataFrame of predictions
        """
        logger.info(f"Saving {len(predictions_df)} predictions to Snowflake")
        
        try:
            # Convert to records
            records = predictions_df.to_dict('records')
            
            # Insert into Snowflake
            self.sf.bulk_insert('nrfi_db.predictions.daily_predictions', records)
            
            logger.info("Predictions saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving predictions: {e}")
            sentry_sdk.capture_exception(e)
            raise
    
    def get_top_picks(self, predictions_df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
        """Get top prediction picks based on edge and confidence.
        
        Args:
            predictions_df: DataFrame of all predictions
            top_n: Number of top picks to return
            
        Returns:
            DataFrame of top picks
        """
        # Filter to only NRFI/YRFI recommendations (exclude PASS)
        picks = predictions_df[predictions_df['recommendation'] != 'PASS'].copy()
        
        # Sort by confidence
        picks = picks.sort_values('confidence', ascending=False).head(top_n)
        
        return picks
    
    def generate_report(self, predictions_df: pd.DataFrame) -> str:
        """Generate text summary of predictions.
        
        Args:
            predictions_df: DataFrame of predictions
            
        Returns:
            Text summary
        """
        report = []
        report.append(f"NRFI/YRFI Predictions for {predictions_df.iloc[0]['game_date']}")
        report.append(f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("-" * 60)
        report.append(f"\nTotal games: {len(predictions_df)}")
        
        nrfi_recs = len(predictions_df[predictions_df['recommendation'] == 'NRFI'])
        yrfi_recs = len(predictions_df[predictions_df['recommendation'] == 'YRFI'])
        pass_recs = len(predictions_df[predictions_df['recommendation'] == 'PASS'])
        
        report.append(f"NRFI recommendations: {nrfi_recs}")
        report.append(f"YRFI recommendations: {yrfi_recs}")
        report.append(f"Pass (low confidence): {pass_recs}")
        
        report.append("\n" + "=" * 60)
        report.append("\nTop Picks:")
        report.append("=" * 60)
        
        top_picks = self.get_top_picks(predictions_df, top_n=5)
        
        for idx, pick in top_picks.iterrows():
            report.append(f"\n{pick['away_team']} @ {pick['home_team']} ({pick['game_time']})")
            report.append(f"  Recommendation: {pick['recommendation']}")
            report.append(f"  Confidence: {pick['confidence']:.1%}")
            report.append(f"  NRFI Prob: {pick['nrfi_probability']:.1%}")
            if pick['edge_vs_odds']:
                report.append(f"  Edge vs Odds: {pick['edge_vs_odds']:+.2%}")
        
        return "\n".join(report)


def main():
    """Main daily prediction pipeline."""
    logger.info("Starting daily NRFI prediction pipeline")
    
    try:
        # Initialize predictor
        predictor = NFRIDailyPredictor()
        
        # Get today's games
        games = predictor.get_todays_games()
        
        if not games:
            logger.warning("No games scheduled for today")
            return
        
        # Generate predictions
        predictions = predictor.generate_predictions(games)
        
        # Save to Snowflake
        predictor.save_predictions(predictions)
        
        # Generate report
        report = predictor.generate_report(predictions)
        print(report)
        
        # Save report to file
        report_path = f"/tmp/nrfi_predictions_{datetime.now().strftime('%Y%m%d')}.txt"
        with open(report_path, 'w') as f:
            f.write(report)
        logger.info(f"Report saved to {report_path}")
        
        # Log to PostHog
        try:
            import posthog
            if os.getenv('POSTHOG_API_KEY'):
                posthog.capture(
                    'daily_predictions_generated',
                    {
                        'num_games': len(games),
                        'num_predictions': len(predictions),
                        'nrfi_recs': len(predictions[predictions['recommendation'] == 'NRFI']),
                        'yrfi_recs': len(predictions[predictions['recommendation'] == 'YRFI']),
                    }
                )
        except Exception as e:
            logger.warning(f"PostHog logging failed: {e}")
        
        logger.info("Daily predictions complete")
        
    except Exception as e:
        logger.error(f"Daily prediction failed: {e}")
        sentry_sdk.capture_exception(e)
        raise


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    main()
